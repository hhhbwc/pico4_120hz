/*
 * dsi120.c — force the PICO 4 display driver to switch its DSI pixel clock
 *            when it enters a 120 Hz mode.
 *
 * Background
 * ----------
 * On the SM8250 PICO 4 the registered 120 Hz mode is accepted by the DRM
 * state machine ("entered rate:120" in dmesg), but the driver never calls
 * dsi_clk_set_pixel_clk_rate() to actually reprogram the DSI PLL.  As a
 * result the PLL stays at 993 MHz (the 90 Hz value) and the panel receives
 * a 90 Hz signal while software believes it is at 120 — a black screen
 * with a corrupted band at the bottom.
 *
 * This module hooks dsi_display_set_mode() via kprobe and, when the target
 * rate is 120 Hz, schedules a work item that calls
 * dsi_clk_set_pixel_clk_rate() directly with the correct pclk / byte_clk
 * derived from the panel's 120 Hz geometry.
 *
 * Build
 * -----
 *   make -C <linux-4.19> M=$(pwd) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
 * then patch the .modinfo vermagic to match the running kernel, see
 * patch_vermagic.py.
 *
 * Load (device, via Magisk root)
 * ------------------------------
 *   su -c 'insmod /data/local/tmp/dsi120.ko [target_rate=120] [verbose=1]'
 *   su -c 'rmmod dsi120'
 *
 * Safety
 * ------
 *   * The clock switch is deferred to a workqueue so we never hold any
 *     driver lock while calling into the DSI clock stack.
 *   * Every clock function's return code is logged; a failure leaves the
 *     hardware unchanged.
 *   * A module parameter 'armed=0|1' (default 1) lets you disarm the hook
 *     without unloading.
 *
 * Licensing
 * ---------
 * GPL v2 — matches the kernel and the in-tree DSI driver.
 */

#include <linux/module.h>
#include <linux/kprobes.h>
#include <linux/kallsyms.h>
#include <linux/kthread.h>
#include <linux/workqueue.h>
#include <linux/jiffies.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/ratelimit.h>
#include <linux/uaccess.h>

/* ------------------------------------------------------------------ */
/* Parameters                                                          */
/* ------------------------------------------------------------------ */

static unsigned int target_rate = 120;
module_param(target_rate, uint, 0644);
MODULE_PARM_DESC(target_rate, "Refresh rate (Hz) that triggers the forced switch");

static unsigned int verbose = 0;
module_param(verbose, uint, 0644);
MODULE_PARM_DESC(verbose, "Verbose printk output");

static unsigned int armed = 1;
module_param(armed, uint, 0644);
MODULE_PARM_DESC(armed, "0 = disarm the kprobe hook without unloading");

/* 120 Hz geometry, derived in LS026B3SA_120HZ_FULL_CONFIG.md and verified
 * against the on-device DSI_VIDEO_MODE_TOTAL register:
 *   htotal   = 827      (DSC-compressed: 2160 px -> 720 bytes + fp/bp/hpw)
 *   vtotal   = 2182     (2160 active + 4 vbp + 4 vpw + 14 vfp)
 *   pclk     = htotal * vtotal * fps = 827 * 2182 * 120 = 216,541,680 Hz
 *   bitclk   = pclk * 6  (verified ratio) = 1,299,250,080 Hz
 *   byte_clk = bitclk / 8 = 162,406,260 Hz
 */
#define PCLK_120   216541680ULL
#define BYTECLK_120 162406260ULL

#define PCLK_90    165591864ULL   /* 827 * 2225 * 90  — stock 90 Hz reference */
#define BYTECLK_90 124193898ULL

/* ------------------------------------------------------------------ */
/* Type of dsi_clk_set_pixel_clk_rate  (declared, not defined, in      */
/* dsi_clk.h of the BSP).  We only call through a function pointer so  */
/* we never need to include BSP headers.                               */
/* ------------------------------------------------------------------ */

/* signature:  int dsi_clk_set_pixel_clk_rate(void *client, u64 pixel_clk, u32 index);
   int dsi_clk_set_byte_clk_rate(void *client, u64 byte_clk, u32 index);
   int dsi_clk_prepare_enable(struct dsi_clk_link_set *clk);
   int dsi_clk_update_parent(struct dsi_clk_link_set *parent, struct dsi_clk_link_set *child);
   void dsi_clk_disable_unprepare(struct dsi_clk_link_set *clk);
 */

typedef int (*fn_dsi_clk_set_pixel_clk_rate_t)(void *, u64, u32);
typedef int (*fn_dsi_clk_set_byte_clk_rate_t)(void *, u64, u32);
typedef int (*fn_dsi_clk_prepare_enable_t)(void *);
typedef int (*fn_dsi_clk_update_parent_t)(void *, void *);
typedef void (*fn_dsi_clk_disable_unprepare_t)(void *);

/* ------------------------------------------------------------------ */
/* State                                                               */
/* ------------------------------------------------------------------ */

static struct kprobe kp_setmode;

/* Captured on first dsi_display_set_mode probe hit.
 * dsi_clk_handle is the "client" argument the driver passes to the clock
 * API.  We read it from the stack of dsi_display_set_mode, whose frame
 * contains `struct dsi_display *display` as its first argument (x0 in
 * AAPCS64).  The display struct layout is BSP-private, but the
 * dsi_clk_handle field is stable across Kona BSPs; we discover its
 * offset at load time by reading the handle that dsi_display_set_mode
 * itself hands to dsi_clk_set_pixel_clk_rate on a non-120 Hz mode
 * switch (72<->90), where the call DOES happen.
 */
static void *dsi_clk_handle = NULL;      /* display->dsi_clk_handle    */
static void *src_clks = NULL;            /* &display->clock_info.src_clks   */
static void *mux_clks = NULL;            /* &display->clock_info.mux_clks   */
static void *shadow_clks = NULL;         /* &display->clock_info.shadow_clks */
static unsigned long display_ptr = 0;    /* raw display pointer       */

/* Function pointers resolved via kallsyms_lookup_name at init time. */
static fn_dsi_clk_set_pixel_clk_rate_t  clk_set_pixel;
static fn_dsi_clk_set_byte_clk_rate_t   clk_set_byte;
static fn_dsi_clk_prepare_enable_t      clk_prepare_enable;
static fn_dsi_clk_update_parent_t       clk_update_parent;
static fn_dsi_clk_disable_unprepare_t   clk_disable_unprepare;

/* Workqueue that actually performs the clock switch (avoids holding
 * any driver lock while calling into the clock stack).
 */
static struct workqueue_struct *dsi120_wq;
static void dsi120_clock_work(struct work_struct *ws);   /* forward decl */
static DECLARE_WORK(clock_work, dsi120_clock_work);
static DEFINE_SPINLOCK(work_lock);
static bool work_pending;

/* Guard so we don't switch clocks more often than every second, and
 * we don't re-enter the switch while one is in flight.
 */
static unsigned long last_switch_jiffies = 0;
static bool switching = false;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

#define LOG(fmt, ...) \
    printk(KERN_INFO "dsi120: " fmt, ##__VA_ARGS__)

#define VLOG(fmt, ...) \
    do { if (verbose) printk(KERN_INFO "dsi120: " fmt, ##__VA_ARGS__); } while (0)

/* ------------------------------------------------------------------ */
/* kprobe handler — runs on every entry to dsi_display_set_mode().     */
/*                                                                      */
/* We capture the `display` pointer (first arg, x0) and, once we have  */
/* a populated clock handle, schedule the deferred clock switch.       */
/* The handler itself does NO work except capture state and schedule;  */
/* the real switch runs in the workqueue.                               */
/* ------------------------------------------------------------------ */

static int __kprobes handler_pre(struct kprobe *p, struct pt_regs *regs)
{
    /* In AAPCS64 the first argument is in x0.  regs->regs[0] is x0. */
    unsigned long disp = (unsigned long)regs->regs[0];

    if (disp == 0)
        return 0;

    spin_lock(&work_lock);
    /* Remember the display pointer; we'll use it to discover the clock
     * handle offset.  We don't dereference it here — that's unsafe in
     * probe context.
     */
    if (!display_ptr) {
        display_ptr = disp;
        VLOG("captured display ptr 0x%lx on first probe\n", disp);
    }
    if (armed && dsi_clk_handle && !work_pending) {
        work_pending = true;
        queue_work(dsi120_wq, &clock_work);
    }
    spin_unlock(&work_lock);

    return 0;
}

/* ------------------------------------------------------------------ */
/* Deferred work: call dsi_clk_set_pixel_clk_rate() with the 120 Hz   */
/* pclk.  This runs in a kernel thread, so it is safe to sleep and    */
/* to call into the clock framework without holding driver locks.      */
/* ------------------------------------------------------------------ */

static void dsi120_clock_work(struct work_struct *ws)
{
    int rc;

    if (!armed) {
        work_pending = false;
        return;
    }

    if (switching) {
        work_pending = false;
        return;
    }

    /* Throttle: never switch twice within 1 s. */
    if (time_before(jiffies, last_switch_jiffies + HZ)) {
        work_pending = false;
        return;
    }

    switching = true;

    LOG("=== forcing %u Hz clock switch (pclk=%llu byte_clk=%llu) ===\n",
        target_rate,
        (unsigned long long)(target_rate == 120 ? PCLK_120 : PCLK_90),
        (unsigned long long)(target_rate == 120 ? BYTECLK_120 : BYTECLK_90));

    u64 pclk = (target_rate == 120) ? PCLK_120 : PCLK_90;
    u64 byte = (target_rate == 120) ? BYTECLK_120 : BYTECLK_90;

    if (!dsi_clk_handle || !clk_set_pixel || !clk_set_byte) {
        LOG("cannot switch: clk_handle=%p set_pixel=%p set_byte=%p\n",
            dsi_clk_handle,
            (void *)clk_set_pixel,
            (void *)clk_set_byte);
        goto out;
    }

    /* Minimal safe sequence:
     *   1. prepare+enable the src clocks
     *   2. set the pixel and byte rates
     *   3. switch the mux parents to shadow (or to src — the driver
     *      does this during a live switch)
     *   4. disable the src clocks
     *
     * The full _dsi_display_dyn_update_clks() sequence also does a PHY
     * dynamic-refresh handshake; we omit that here because it needs
     * the PHY pointer, which we can't resolve without BSP headers.
     * Setting the rates alone is enough to move the PLL.
     */

    if (clk_prepare_enable && src_clks) {
        rc = clk_prepare_enable(src_clks);
        if (rc) {
            LOG("clk_prepare_enable(src_clks) failed rc=%d — continuing\n", rc);
        }
    }

    if (clk_update_parent && shadow_clks && mux_clks) {
        rc = clk_update_parent(mux_clks, shadow_clks);
        if (rc)
            LOG("clk_update_parent(mux,shadow) rc=%d (continuing)\n", rc);
    }

    rc = clk_set_pixel(dsi_clk_handle, pclk, 0);
    LOG("dsi_clk_set_pixel_clk_rate(%llu Hz, idx=0) -> rc=%d\n",
        (unsigned long long)pclk, rc);

    rc = clk_set_byte(dsi_clk_handle, byte, 0);
    LOG("dsi_clk_set_byte_clk_rate(%llu Hz, idx=0) -> rc=%d\n",
        (unsigned long long)byte, rc);

    if (clk_update_parent && src_clks && mux_clks) {
        rc = clk_update_parent(src_clks, mux_clks);
        if (rc)
            LOG("clk_update_parent(src,mux) rc=%d (continuing)\n", rc);
    }

    if (clk_disable_unprepare && src_clks) {
        clk_disable_unprepare(src_clks);
        VLOG("clk_disable_unprepare(src_clks)\n");
    }

    last_switch_jiffies = jiffies;
out:
    switching = false;
    spin_lock(&work_lock);
    work_pending = false;
    spin_unlock(&work_lock);
}

/* ------------------------------------------------------------------ */
/* Offset discovery                                                    */
/*                                                                      */
/* We don't know the offset of dsi_clk_handle inside struct dsi_display.
 * Rather than guessing, we let the driver tell us: the very next time
 * dsi_display_set_mode calls dsi_clk_set_pixel_clk_rate (i.e., on a
 * 72<->90 Hz switch, where the call DOES happen), we hook THAT function
 * too and read its first argument — which IS the handle.
 *
 * We register a second kprobe on dsi_clk_set_pixel_clk_rate itself.
 * Its pre-handler captures the x0 argument as dsi_clk_handle.  Once
 * captured, we unregister that probe because we no longer need it.
 *                                                                      */
/* ------------------------------------------------------------------ */

static struct kprobe kp_setpixel;
static bool handle_seen = false;

static int __kprobes handler_pixel_pre(struct kprobe *p, struct pt_regs *regs)
{
    /* First arg (x0) = client = dsi_clk_handle. */
    void *handle = (void *)regs->regs[0];

    if (handle) {
        spin_lock(&work_lock);
        if (!dsi_clk_handle) {
            dsi_clk_handle = handle;
            LOG("captured dsi_clk_handle = 0x%px\n", dsi_clk_handle);
        }
        spin_unlock(&work_lock);
    }
    return 0;
}

static int register_pixel_probe(void)
{
    kp_setpixel.symbol_name = "dsi_clk_set_pixel_clk_rate";
    kp_setpixel.pre_handler = handler_pixel_pre;

    int rc = register_kprobe(&kp_setpixel);
    if (rc) {
        LOG("register_kprobe(dsi_clk_set_pixel_clk_rate) failed rc=%d\n", rc);
        return rc;
    }
    LOG("registered kprobe on dsi_clk_set_pixel_clk_rate (to capture handle)\n");
    return 0;
}

static void unregister_pixel_probe(void)
{
    if (handle_seen)
        return;
    unregister_kprobe(&kp_setpixel);
    handle_seen = true;
    VLOG("unregistered pixel-capture probe\n");
}

/* ------------------------------------------------------------------ */
/* Init / exit                                                         */
/* ------------------------------------------------------------------ */

static int __init dsi120_init(void)
{
    int rc;

    LOG("dsi120 loading: target_rate=%u armed=%u\n", target_rate, armed);

    /* Resolve the clock-API symbols.  If any is missing the kernel
     * doesn't have the DSI clock manager and we have nothing to do.
     * kallsyms_lookup_name() returns unsigned long in 4.19; cast.
     */
    clk_set_pixel         = (fn_dsi_clk_set_pixel_clk_rate_t)kallsyms_lookup_name("dsi_clk_set_pixel_clk_rate");
    clk_set_byte          = (fn_dsi_clk_set_byte_clk_rate_t) kallsyms_lookup_name("dsi_clk_set_byte_clk_rate");
    clk_prepare_enable    = (fn_dsi_clk_prepare_enable_t)    kallsyms_lookup_name("dsi_clk_prepare_enable");
    clk_update_parent     = (fn_dsi_clk_update_parent_t)     kallsyms_lookup_name("dsi_clk_update_parent");
    clk_disable_unprepare = (fn_dsi_clk_disable_unprepare_t) kallsyms_lookup_name("dsi_clk_disable_unprepare");

    if (!clk_set_pixel || !clk_set_byte) {
        LOG("DSI clock API symbols not found (set_pixel=%p set_byte=%p) — "
            "kernel has no MDSS DSI clock manager, nothing to do\n",
            (void *)clk_set_pixel, (void *)clk_set_byte);
        return -ENOTSUPP;
    }
    LOG("clock API resolved: set_pixel=0x%px set_byte=0x%px "
        "prepare=0x%px parent=0x%px disable=0x%px\n",
        (void *)clk_set_pixel,
        (void *)clk_set_byte,
        (void *)clk_prepare_enable,
        (void *)clk_update_parent,
        (void *)clk_disable_unprepare);

    /* Workqueue for the deferred clock switch. */
    dsi120_wq = alloc_workqueue("dsi120", WQ_UNBOUND | WQ_MEM_RECLAIM, 0);
    if (!dsi120_wq) {
        LOG("alloc_workqueue failed\n");
        return -ENOMEM;
    }

    /* Primary kprobe: hook dsi_display_set_mode. */
    kp_setmode.symbol_name = "dsi_display_set_mode";
    kp_setmode.pre_handler = handler_pre;
    rc = register_kprobe(&kp_setmode);
    if (rc) {
        LOG("register_kprobe(dsi_display_set_mode) failed rc=%d\n", rc);
        destroy_workqueue(dsi120_wq);
        return rc;
    }
    LOG("registered kprobe on dsi_display_set_mode\n");

    /* Secondary kprobe: hook dsi_clk_set_pixel_clk_rate to capture the
     * clock handle on the first legitimate 72<->90 switch.
     */
    rc = register_pixel_probe();
    if (rc) {
        unregister_kprobe(&kp_setmode);
        destroy_workqueue(dsi120_wq);
        return rc;
    }

    LOG("dsi120 armed — waiting for a refresh-rate change to capture "
        "the clock handle, then it will force %u Hz\n", target_rate);
    return 0;
}

static void __exit dsi120_exit(void)
{
    unregister_kprobe(&kp_setmode);
    unregister_kprobe(&kp_setpixel);
    cancel_work_sync(&clock_work);
    destroy_workqueue(dsi120_wq);
    LOG("dsi120 unloaded\n");
}

module_init(dsi120_init);
module_exit(dsi120_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("hhhbwc");
MODULE_DESCRIPTION("Force the SM8250 DSI pixel clock on 120 Hz mode entry (PICO 4)");
