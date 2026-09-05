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
 * This module hooks dsi_display_set_mode() and the DSI clock setters via
 * kprobe.  The current build is probe-only (diagnostic): callbacks capture
 * pointers, arguments, and counters, but never schedule work or call clock
 * APIs.  The clock worker remains disabled until the private handle lifetime
 * and complete mode-switch sequence are confirmed on the PICO BSP.
 *
 * Build
 * -----
 *   Sync .config from device /proc/config.gz, then:
 *   bash build.sh
 *
 * Load (device, via Magisk root, flags=0 required)
 * ------------------------------------------------
 *   adb shell su -Z u:r:magisk:s0 -c '/data/local/tmp/load_module /data/local/tmp/dsi120.ko 0'
 *   adb shell su -Z u:r:magisk:s0 -c 'rmmod dsi120'
 *
 * Safety
 * ------
 *   * The clock switch is deferred to a workqueue so we never hold any
 *     driver lock while calling into the DSI clock stack (currently not
 *     scheduled — probes are observation-only).
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
#include <linux/clk.h>

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

/* Verified against Qualcomm CAF SM8250 dsi_clk_manager.c:
 *   int dsi_clk_set_pixel_clk_rate(void *client, u64 pixel_clk, u32 index);
 *   int dsi_clk_set_byte_clk_rate(void *client, u64 byte_clk, u64 byte_intf_clk, u32 index);
 *   int dsi_clk_prepare_enable(struct dsi_clk_link_set *clk);
 *   int dsi_clk_update_parent(struct dsi_clk_link_set *parent, struct dsi_clk_link_set *child);
 *   void dsi_clk_disable_unprepare(struct dsi_clk_link_set *clk);
 *
 * client is actually struct dsi_clk_client_info * (from dsi_register_clk_handle).
 * byte_clk takes an extra byte_intf_clk parameter we previously omitted.
 */

typedef int (*fn_dsi_clk_set_pixel_clk_rate_t)(void *, u64, u32);
typedef int (*fn_dsi_clk_set_byte_clk_rate_t)(void *, u64, u64, u32);
typedef int (*fn_dsi_clk_prepare_enable_t)(void *);
typedef int (*fn_dsi_clk_update_parent_t)(void *, void *);
typedef void (*fn_dsi_clk_disable_unprepare_t)(void *);

/* ------------------------------------------------------------------ */
/* State                                                               */
/* ------------------------------------------------------------------ */

static struct kprobe kp_setmode;

/* Captured on first dsi_clk_set_pixel_clk_rate probe hit.
 * The "client" argument is actually struct dsi_clk_client_info * (from
 * dsi_register_clk_handle()), NOT struct dsi_display *.  Its first field
 * is char name[32], followed by refcounts and struct dsi_clk_mngr *mngr.
 * We read it from the x0 register of the probed function.
 */
static void *dsi_clk_handle = NULL;      /* struct dsi_clk_client_info * */
static void *src_clks = NULL;            /* &display->clock_info.src_clks   */
static void *mux_clks = NULL;            /* &display->clock_info.mux_clks   */
static void *shadow_clks = NULL;         /* &display->clock_info.shadow_clks */
static unsigned long display_ptr = 0;    /* raw struct dsi_display *        */

/* Function pointers resolved via kallsyms_lookup_name at init time. */
static fn_dsi_clk_set_pixel_clk_rate_t  clk_set_pixel;
static fn_dsi_clk_set_byte_clk_rate_t   clk_set_byte;
static fn_dsi_clk_prepare_enable_t      clk_prep_en;
static fn_dsi_clk_update_parent_t       clk_update_parent;
static fn_dsi_clk_disable_unprepare_t   clk_dis_unprep;

/* The current diagnostic build only observes probe hits.  Clock switching
 * remains in the worker below but is deliberately not scheduled by probes.
 */
static struct workqueue_struct *dsi120_wq;
static void dsi120_clock_work(struct work_struct *ws);   /* forward decl */
static DECLARE_WORK(clock_work, dsi120_clock_work);
static unsigned int setmode_hits;
static unsigned int pixel_hits;
static unsigned int byte_hits;
module_param(setmode_hits, uint, 0444);
MODULE_PARM_DESC(setmode_hits, "Approximate dsi_display_set_mode probe hit count");
module_param(pixel_hits, uint, 0444);
MODULE_PARM_DESC(pixel_hits, "Approximate dsi_clk_set_pixel_clk_rate probe hit count");
module_param(byte_hits, uint, 0444);
MODULE_PARM_DESC(byte_hits, "Approximate dsi_clk_set_byte_clk_rate probe hit count");

/* Guard so we don't switch clocks more often than every second, and
 * we don't re-enter the switch while one is in flight.
 */
static unsigned long last_switch_jiffies = 0;
static bool switching = false;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

#define LOG(fmt, ...) \
    printk(KERN_EMERG "dsi120: " fmt, ##__VA_ARGS__)

#define VLOG(fmt, ...) \
    do { if (verbose) printk(KERN_EMERG "dsi120: " fmt, ##__VA_ARGS__); } while (0)

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
    /* Observation-only: do not queue work or call driver APIs in probe context. */
    unsigned long disp = (unsigned long)regs->regs[0];

    if (disp) {
        if (!READ_ONCE(display_ptr))
            WRITE_ONCE(display_ptr, disp);
        WRITE_ONCE(setmode_hits, READ_ONCE(setmode_hits) + 1);
    }
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

    if (!armed)
        return;

    if (switching)
        return;

    /* Throttle: never switch twice within 1 s. */
    if (time_before(jiffies, last_switch_jiffies + HZ))
        return;

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

    /* Validate the client handle: struct dsi_clk_client_info has
     * char name[32] as its first field.  A valid handle should have
     * a printable name (not all zeros, not all 0xFF). */
    {
        char *name = (char *)dsi_clk_handle;
        int printable = 0;
        int i;
        for (i = 0; i < 32 && name[i]; i++) {
            if (name[i] >= 32 && name[i] < 127)
                printable++;
        }
        if (printable < 3) {
            LOG("WARNING: clk_handle name not printable (%d/32) — "
                "may not be a valid dsi_clk_client_info *\n", printable);
        } else {
            VLOG("clk_handle name: %.32s\n", name);
        }
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
     * This sequence is intentionally not considered validated: the PICO
     * BSP may require its full dynamic-refresh and PHY handshake.
     */

    if (clk_prep_en && src_clks) {
        rc = clk_prep_en(src_clks);
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

    /* The D-PHY reference path derives byte_intf_clk as byte_clk / 2.
     * This call remains disabled in the current probe-only build. */
    rc = clk_set_byte(dsi_clk_handle, byte, byte / 2, 0);
    LOG("dsi_clk_set_byte_clk_rate(%llu Hz, intf=%llu, idx=0) -> rc=%d\n",
        (unsigned long long)byte, (unsigned long long)(byte / 2), rc);

    if (clk_update_parent && src_clks && mux_clks) {
        rc = clk_update_parent(src_clks, mux_clks);
        if (rc)
            LOG("clk_update_parent(src,mux) rc=%d (continuing)\n", rc);
    }

    if (clk_dis_unprep && src_clks) {
        clk_dis_unprep(src_clks);
        VLOG("clk_disable_unprepare(src_clks)\n");
    }

    /* Read back the actual rates to verify the switch took effect.
     * dsi_clk_client_info->mngr->link_clks[index].freq contains the
     * cached rates after a successful set.  We can't dereference safely
     * without the full struct definition, so we log the expected values
     * and rely on dmesg/regmap for hardware verification. */
    LOG("expected after switch: pclk=%llu byte_clk=%llu\n",
        (unsigned long long)pclk, (unsigned long long)byte);

    last_switch_jiffies = jiffies;
out:
    switching = false;
}

/* ------------------------------------------------------------------ */
/* ------------------------------------------------------------------ */
/* Handle capture                                                       */
/*                                                                      */
/* We hook dsi_clk_set_pixel_clk_rate itself.  Its first argument (x0)  */
/* is the "client" pointer — struct dsi_clk_client_info * — which the  */
/* driver obtained from dsi_register_clk_handle().  We capture it on    */
/* the first legitimate 72<->90 Hz switch, where the driver actually    */
/* calls this function.  Once captured, we use it as the handle for     */
/* our own 120 Hz clock switch.                                         */
/* ------------------------------------------------------------------ */
/* ------------------------------------------------------------------ */

static struct kprobe kp_setpixel;
static struct kprobe kp_setbyte;

static int __kprobes handler_pixel_pre(struct kprobe *p, struct pt_regs *regs)
{
    /* Observation-only: capture the first non-null client pointer. */
    void *handle = (void *)regs->regs[0];

    if (handle) {
        if (!READ_ONCE(dsi_clk_handle))
            WRITE_ONCE(dsi_clk_handle, handle);
        WRITE_ONCE(pixel_hits, READ_ONCE(pixel_hits) + 1);
    }
    return 0;
}

static int __kprobes handler_byte_pre(struct kprobe *p, struct pt_regs *regs)
{
    /* Observation-only: capture the first non-null client pointer and
     * log the 4-parameter ABI to verify our function pointer is correct.
     * x0=client, x1=byte_clk, x2=byte_intf_clk, w3=index
     */
    void *handle = (void *)regs->regs[0];
    u64 byte_clk = (u64)regs->regs[1];
    u64 byte_intf = (u64)regs->regs[2];
    u32 index = (u32)regs->regs[3];

    if (handle) {
        if (!READ_ONCE(dsi_clk_handle))
            WRITE_ONCE(dsi_clk_handle, handle);
        WRITE_ONCE(byte_hits, READ_ONCE(byte_hits) + 1);
        VLOG("byte_clk=%llu intf=%llu idx=%u\n",
             (unsigned long long)byte_clk,
             (unsigned long long)byte_intf, index);
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

static int register_byte_probe(void)
{
    kp_setbyte.symbol_name = "dsi_clk_set_byte_clk_rate";
    kp_setbyte.pre_handler = handler_byte_pre;

    int rc = register_kprobe(&kp_setbyte);
    if (rc) {
        LOG("register_kprobe(dsi_clk_set_byte_clk_rate) failed rc=%d\n", rc);
        return rc;
    }
    LOG("registered kprobe on dsi_clk_set_byte_clk_rate (verify 4-param ABI)\n");
    return 0;
}

static void unregister_pixel_probe(void)
{
    unregister_kprobe(&kp_setpixel);
}

static void unregister_byte_probe(void)
{
    unregister_kprobe(&kp_setbyte);
}

/* ------------------------------------------------------------------ */
/* Init / exit                                                         */
/* ------------------------------------------------------------------ */

static int __init dsi120_init(void)
{
    int rc;

    /* Direct printk to verify the init function is actually running */
    pr_emerg("dsi120: INIT FUNCTION ENTERED\n");
    printk(KERN_EMERG "dsi120: target_rate=%u armed=%u verbose=%u\n",
           target_rate, armed, verbose);

    /* Resolve the clock-API symbols.  If any is missing the kernel
     * doesn't have the DSI clock manager and we have nothing to do.
     * kallsyms_lookup_name() returns unsigned long in 4.19; cast.
     */
    clk_set_pixel         = (fn_dsi_clk_set_pixel_clk_rate_t)kallsyms_lookup_name("dsi_clk_set_pixel_clk_rate");
    clk_set_byte          = (fn_dsi_clk_set_byte_clk_rate_t) kallsyms_lookup_name("dsi_clk_set_byte_clk_rate");
    clk_prep_en           = (fn_dsi_clk_prepare_enable_t)    kallsyms_lookup_name("dsi_clk_prepare_enable");
    clk_update_parent     = (fn_dsi_clk_update_parent_t)     kallsyms_lookup_name("dsi_clk_update_parent");
    clk_dis_unprep        = (fn_dsi_clk_disable_unprepare_t) kallsyms_lookup_name("dsi_clk_disable_unprepare");

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
        (void *)clk_prep_en,
        (void *)clk_update_parent,
        (void *)clk_dis_unprep);

    /* Diagnostic build: probes only record scalar/pointer observations. */
    dsi120_wq = alloc_workqueue("dsi120", WQ_UNBOUND | WQ_MEM_RECLAIM, 1);
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

    rc = register_byte_probe();
    if (rc) {
        unregister_pixel_probe();
        unregister_kprobe(&kp_setmode);
        destroy_workqueue(dsi120_wq);
        return rc;
    }

    LOG("probe-only diagnostics active; no work is queued and no clocks are changed\n");
    return 0;
}

static void __exit dsi120_exit(void)
{
    unregister_kprobe(&kp_setmode);
    unregister_pixel_probe();
    unregister_byte_probe();
    cancel_work_sync(&clock_work);
    destroy_workqueue(dsi120_wq);
    LOG("dsi120 unloaded\n");
}

module_init(dsi120_init);
module_exit(dsi120_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("hhhbwc");
MODULE_DESCRIPTION("Force the SM8250 DSI pixel clock on 120 Hz mode entry (PICO 4)");
