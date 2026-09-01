package com.picoxr.refreshselector;

import android.app.Activity;
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.provider.Settings;
import android.view.Display;
import android.view.View;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.CompoundButton;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public final class RefreshRateHook implements IXposedHookLoadPackage {
    private static final String TAG = "PicoRefreshSelector";
    private static final String SETTINGS_PACKAGE = "com.picovr.settings";
    private static final int REFRESH_SWITCH_ID = 0x7f0902c6;
    private static final String CHOICE_KEY = "pico_refresh_selector_choice";
    // The stock flow reboots straight after the selection. Staging the vendor
    // state and leaving the reboot to the user keeps the timing under control
    // and makes it possible to confirm the write before restarting.
    private static final String AUTO_RESTART_KEY = "pico_refresh_selector_auto_restart";
    // DisplayModeDirector reports "unknown display" for id 0 and hands
    // SurfaceFlinger an empty allowed set, which pins the panel to the default
    // config. SurfaceFlinger's debug transaction 1035 pins a config directly and
    // makes it ignore later allowed-config updates.
    private static final String LIVE_SWITCH_KEY = "pico_refresh_selector_live_switch";
    // One-shot trigger so the pin can be exercised without touching the headset UI.
    private static final String PIN_NOW_KEY = "pico_refresh_selector_pin_now";
    private static final int SF_SET_ALLOWED_CONFIG = 1035;
    private static final int[] RATES = {72, 90, 120};

    private static final ThreadLocal<Boolean> OPENING_REFRESH_MENU = new ThreadLocal<>();
    private static final Map<Object, List<Integer>> REFRESH_LISTENERS =
            Collections.synchronizedMap(new WeakHashMap<>());

    @Override
    public void handleLoadPackage(final XC_LoadPackage.LoadPackageParam lp) {
        if (!SETTINGS_PACKAGE.equals(lp.packageName)) {
            return;
        }

        try {
            hookRefreshSwitch(lp.classLoader);
            hookRefreshDropdown(lp.classLoader);
            hookPopupBuilder(lp.classLoader);
            hookPopupClick(lp.classLoader);
            hookVendorStateProbe(lp.classLoader);
            hookCapabilityGate(lp.classLoader);
            XposedBridge.log(TAG + ": installed native PICO refresh popup hooks");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": hook installation failed: " + error);
        }
    }

    // Constant.i() only reports 120 Hz capability for ro.pvr.product.name
    // "FalconCV3", so on Phoenix every stock string and branch degrades 120 to
    // 90. Reporting the unit as capable keeps the vendor UI text consistent
    // with the DTBO that now enumerates 120 Hz.
    private static void hookCapabilityGate(final ClassLoader loader) {
        try {
            XposedHelpers.findAndHookMethod(
                    XposedHelpers.findClass("com.picovr.utils.Utils", loader), "s1",
                    new XC_MethodHook() {
                        @Override
                        protected void afterHookedMethod(MethodHookParam param) {
                            param.setResult(Boolean.TRUE);
                        }
                    });
            XposedBridge.log(TAG + ": forced 120-capable capability gate");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": capability gate hook failed: " + error);
        }
    }

    // Read-only diagnostics. The refresh rate that survives a reboot comes from
    // the PICO configuration service, not from persist.pvr.display.type, so the
    // stored keys have to be observable before anything else can be trusted.
    private static void hookVendorStateProbe(final ClassLoader loader) {
        Class<?> application = XposedHelpers.findClass(
                "com.picovr.settings.SettingApplication", loader);
        XposedHelpers.findAndHookMethod(application, "onCreate", new XC_MethodHook() {
            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                new Thread(() -> {
                    try {
                        Thread.sleep(4000);
                    } catch (InterruptedException ignored) {
                        return;
                    }
                    logVendorState(loader);
                }, "PicoRefreshProbe").start();
            }
        });
    }

    private static void logVendorState(ClassLoader loader) {
        XposedBridge.log(TAG + ": --- vendor state probe ---");
        logConfigValue(loader, "sdk_refreshRate");
        logConfigValue(loader, "sdk_Recommand_refreshRate");
        XposedBridge.log(TAG + ": prop persist.pvr.display.type="
                + getProperty("persist.pvr.display.type", "?"));
        XposedBridge.log(TAG + ": prop sys.pvr.display.type="
                + getProperty("sys.pvr.display.type", "?"));
        try {
            Object utils = XposedHelpers.findClass("com.picovr.utils.Utils", loader);
            XposedBridge.log(TAG + ": Utils.s1() (120-capable)="
                    + XposedHelpers.callStaticMethod((Class<?>) utils, "s1"));
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": Utils.s1() read failed: " + error);
        }
        XposedBridge.log(TAG + ": --- end probe ---");
        maybePinOnRequest(loader);
    }

    private static void maybePinOnRequest(ClassLoader loader) {
        try {
            Context context = (Context) XposedHelpers.callStaticMethod(
                    XposedHelpers.findClass("com.picovr.settings.SettingApplication", loader), "b");
            if (Settings.Global.getInt(context.getContentResolver(), PIN_NOW_KEY, 0) != 1) {
                return;
            }
            Settings.Global.putInt(context.getContentResolver(), PIN_NOW_KEY, 0);
            int rate = currentRate(context);
            XposedBridge.log(TAG + ": pin-now requested for " + rate + " Hz");
            pinSurfaceFlingerConfig(context, rate);
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": pin-now failed: " + error);
        }
    }

    private static void logConfigValue(ClassLoader loader, String key) {
        try {
            Object value = XposedHelpers.callStaticMethod(
                    XposedHelpers.findClass("com.picovr.utils.ConfigServiceManager", loader),
                    "f", key, "<unset>");
            XposedBridge.log(TAG + ": config " + key + "=" + value);
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": config " + key + " read failed: " + error);
        }
    }

    private static void hookRefreshSwitch(final ClassLoader loader) {
        Class<?> fragment = XposedHelpers.findClass(
                "com.picovr.fragments.PicolabFragment", loader);
        XposedHelpers.findAndHookMethod(fragment, "onCheckedChanged",
                CompoundButton.class, boolean.class, new XC_MethodHook() {
                    @Override
                    protected void beforeHookedMethod(MethodHookParam param) {
                        CompoundButton button = (CompoundButton) param.args[0];
                        if (button.getId() != REFRESH_SWITCH_ID || !button.isPressed()) {
                            return;
                        }

                        // The stock control is a SwitchView. Reuse its click as the anchor
                        // for the same PopupMenuHelper surface used by power management.
                        param.setResult(null);
                        button.setChecked(currentRate(button.getContext()) != 72);
                        OPENING_REFRESH_MENU.set(true);
                        try {
                            Method popupMethod = param.thisObject.getClass()
                                    .getDeclaredMethod("T0", View.class);
                            popupMethod.setAccessible(true);
                            popupMethod.invoke(param.thisObject, button);
                        } catch (Throwable error) {
                            XposedBridge.log(TAG + ": failed to open native popup: " + error);
                        } finally {
                            OPENING_REFRESH_MENU.remove();
                        }
                    }
                });
    }

    private static void hookRefreshDropdown(final ClassLoader loader) {
        Class<?> fragment = XposedHelpers.findClass(
                "com.picovr.fragments.PicolabFragment", loader);
        XposedHelpers.findAndHookMethod(fragment, "onCreateView",
                XposedHelpers.findClass("android.view.LayoutInflater", loader),
                XposedHelpers.findClass("android.view.ViewGroup", loader),
                XposedHelpers.findClass("android.os.Bundle", loader), new XC_MethodHook() {
                    @Override
                    protected void afterHookedMethod(MethodHookParam param) {
                        try {
                            Object root = param.getResult();
                            if (!(root instanceof View)) {
                                return;
                            }
                            View switchView = ((View) root).findViewById(REFRESH_SWITCH_ID);
                            if (switchView == null || !(switchView.getParent() instanceof android.view.ViewGroup)) {
                                return;
                            }
                            android.view.ViewGroup parent = (android.view.ViewGroup) switchView.getParent();
                            int index = parent.indexOfChild(switchView);
                            android.view.ViewGroup.LayoutParams params = switchView.getLayoutParams();

                            Class<?> dropdownClass = XposedHelpers.findClass(
                                    "com.picovr.customviews.DropdownOptionView", loader);
                            Constructor<?> constructor = dropdownClass.getConstructor(Context.class,
                                    XposedHelpers.findClass("android.util.AttributeSet", loader));
                            View dropdown = (View) constructor.newInstance(switchView.getContext(), null);
                            dropdown.setId(REFRESH_SWITCH_ID);
                            dropdown.setLayoutParams(params);
                            dropdown.setOnClickListener(anchor -> {
                                OPENING_REFRESH_MENU.set(true);
                                try {
                                    Method popupMethod = param.thisObject.getClass()
                                            .getDeclaredMethod("T0", View.class);
                                    popupMethod.setAccessible(true);
                                    popupMethod.invoke(param.thisObject, anchor);
                                } catch (Throwable error) {
                                    XposedBridge.log(TAG + ": failed to open refresh popup: " + error);
                                } finally {
                                    OPENING_REFRESH_MENU.remove();
                                }
                            });
                            parent.removeViewAt(index);
                            parent.addView(dropdown, index);
                            updateDropdownText(param.thisObject, currentRate(switchView.getContext()), loader);
                        } catch (Throwable error) {
                            XposedBridge.log(TAG + ": dropdown replacement failed: " + error);
                        }
                    }
                });
    }

    private static void hookPopupBuilder(final ClassLoader loader) {
        Class<?> helper = XposedHelpers.findClass(
                "com.picovr.customviews.PopupMenuHelper", loader);
        Class<?> listener = XposedHelpers.findClass(
                "com.picovr.listener.SimpleOnItemClickListener", loader);

        XposedHelpers.findAndHookMethod(helper, "c", Activity.class, View.class,
                BaseAdapter.class, listener, int.class, new XC_MethodHook() {
                    @Override
                    protected void beforeHookedMethod(MethodHookParam param) {
                        if (!Boolean.TRUE.equals(OPENING_REFRESH_MENU.get())) {
                            return;
                        }

                        try {
                            BaseAdapter adapter = (BaseAdapter) param.args[2];
                            List<Object> rows = findList(adapter);
                            if (rows == null) {
                                XposedBridge.log(TAG + ": native popup list not found");
                                return;
                            }

                            Context context = (Context) param.args[0];
                            List<Integer> rates = supportedRates(context);
                            replaceRows(rows, rates, loader);
                            param.args[4] = Math.max(0, rates.indexOf(currentRate(context)));
                            REFRESH_LISTENERS.put(param.args[3], rates);
                            adapter.notifyDataSetChanged();
                            XposedBridge.log(TAG + ": injected native popup rates=" + rates);
                        } catch (Throwable error) {
                            XposedBridge.log(TAG + ": popup injection failed: " + error);
                        }
                    }
                });
    }

    private static void hookPopupClick(final ClassLoader loader) {
        Class<?> listener = XposedHelpers.findClass(
                "com.picovr.fragments.PicolabFragment$3", loader);
        XposedHelpers.findAndHookMethod(listener, "onItemClick", AdapterView.class,
                View.class, int.class, long.class, new XC_MethodHook() {
                    @Override
                    protected void beforeHookedMethod(MethodHookParam param) {
                        List<Integer> rates = REFRESH_LISTENERS.remove(param.thisObject);
                        if (rates == null) {
                            return;
                        }

                        int position = (Integer) param.args[2];
                        if (position < 0 || position >= rates.size()) {
                            param.setResult(null);
                            return;
                        }

                        int rate = rates.get(position);
                        Object fragment = findOwningFragment(param.thisObject);
                        View row = (View) param.args[1];
                        int previous = row == null ? -1 : currentRate(row.getContext());
                        param.setResult(null);
                        applyRate(param.thisObject, rate, loader);
                        if (fragment != null) {
                            updateDropdownText(fragment, rate, loader);
                            dismissPopup(fragment);
                            if (rate != previous) {
                                Context context = row == null ? null : row.getContext();
                                if (context != null && !autoRestartEnabled(context)) {
                                    XposedBridge.log(TAG + ": staged " + rate
                                            + " Hz, reboot manually to apply (set "
                                            + AUTO_RESTART_KEY + "=1 to reboot automatically)");
                                } else {
                                    scheduleRestart(fragment);
                                }
                            }
                        }
                    }
                });
    }

    private static Object findOwningFragment(Object listener) {
        for (Class<?> type = listener.getClass(); type != null; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                if (field.getType().getName().equals("com.picovr.fragments.PicolabFragment")) {
                    try {
                        field.setAccessible(true);
                        return field.get(listener);
                    } catch (Throwable ignored) {
                        return null;
                    }
                }
            }
        }
        return null;
    }

    private static List<Integer> supportedRates(Context context) {
        // The DTBO experiment proved 120 is present. Keep all three user-requested
        // choices visible so 90 can be tested through the explicit vendor path.
        ArrayList<Integer> rates = new ArrayList<>();
        for (int rate : RATES) {
            rates.add(rate);
        }
        return rates;
    }

    private static void replaceRows(List<Object> rows, List<Integer> rates, ClassLoader loader)
            throws Exception {
        Class<?> typeClass = XposedHelpers.findClass(
                "com.bytedance.osui.popupmenu.MenuItemType", loader);
        Class<?> dataClass = XposedHelpers.findClass(
                "com.bytedance.osui.popupmenu.MenuItemData", loader);
        Object checkType = Enum.valueOf((Class<? extends Enum>) typeClass, "TYPE_TITLE_CHECK");
        Constructor<?> constructor = dataClass.getConstructor(typeClass);
        Method setTitle = dataClass.getMethod("l", CharSequence.class);

        rows.clear();
        for (int rate : rates) {
            Object item = constructor.newInstance(checkType);
            setTitle.invoke(item, rate + " Hz");
            rows.add(item);
        }
    }

    private static List<Object> findList(Object object) throws IllegalAccessException {
        for (Class<?> type = object.getClass(); type != null; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                if (List.class.isAssignableFrom(field.getType())) {
                    field.setAccessible(true);
                    Object value = field.get(object);
                    if (value instanceof List) {
                        return (List<Object>) value;
                    }
                }
            }
        }
        return null;
    }

    private static int currentRate(Context context) {
        String type = getProperty("persist.pvr.display.type", "jdi49372");
        if ("jdi493120".equalsIgnoreCase(type)) {
            return 120;
        }
        if ("jdi49390".equalsIgnoreCase(type)) {
            return 90;
        }
        int saved = Settings.Global.getInt(context.getContentResolver(), CHOICE_KEY, 72);
        return saved == 90 || saved == 120 ? saved : 72;
    }

    private static void applyRate(Object listener, int rate, ClassLoader loader) {
        try {
            Context context = (Context) XposedHelpers.callStaticMethod(
                    XposedHelpers.findClass("com.picovr.settings.SettingApplication", loader),
                    "b");
            applyVendorRate(context, rate, loader);
            if (Settings.Global.getInt(context.getContentResolver(), LIVE_SWITCH_KEY, 1) == 1) {
                pinSurfaceFlingerConfig(context, rate);
            }
            Settings.Global.putInt(context.getContentResolver(), CHOICE_KEY, rate);
            XposedBridge.log(TAG + ": requested " + rate + " Hz");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": rate request failed: " + error);
        }
    }

    // Utils.v1(boolean) cannot be reused for the upper rate. It picks the panel
    // type from Utils.s1(), which is Constant.i() && Constant.c(), and
    // Constant.i() only accepts ro.pvr.product.name == "FalconCV3". On Phoenix
    // it returns false, so v1(true) writes jdi49390 instead of jdi493120.
    // Every rate is therefore propagated explicitly here.
    private static void applyVendorRate(Context context, int rate, ClassLoader loader) {
        String type;
        switch (rate) {
            case 72:  type = "jdi49372";  break;
            case 90:  type = "jdi49390";  break;
            case 120: type = "jdi493120"; break;
            default: throw new IllegalArgumentException("Unsupported refresh rate: " + rate);
        }
        String value = Integer.toString(rate);

        XposedHelpers.callStaticMethod(
                XposedHelpers.findClass("com.pvr.common.CommonUtils", loader),
                "setSystemProperties", "persist.pvr.display.type", type);

        Class<?> config = XposedHelpers.findClass("com.picovr.utils.ConfigServiceManager", loader);
        XposedHelpers.callStaticMethod(config, "i", "sdk_refreshRate", value);
        XposedHelpers.callStaticMethod(config, "i", "sdk_Recommand_refreshRate", value);

        Class<?> utils = XposedHelpers.findClass("com.picovr.utils.Utils", loader);
        XposedHelpers.callStaticMethod(utils, "P0", "persist.pvr.display.type", rate);
        XposedHelpers.callStaticMethod(utils, "B0", "com.pvr.display.type", rate);
        XposedHelpers.callStaticMethod(utils, "w1", rate == 72 ? 24 : 30);

        XposedBridge.log(TAG + ": vendor state -> " + type + ", sdk_refreshRate=" + value);
    }

    private static void logDisplayConfigState(Class<?> surfaceControl, Object token, String when) {
        try {
            Object active = XposedHelpers.callStaticMethod(surfaceControl, "getActiveConfig", token);
            Object allowed = XposedHelpers.callStaticMethod(
                    surfaceControl, "getAllowedDisplayConfigs", token);
            XposedBridge.log(TAG + ": " + when + " activeConfig=" + active
                    + " allowedConfigs=" + (allowed instanceof int[]
                            ? Arrays.toString((int[]) allowed) : allowed));
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": " + when + " config read failed: " + error);
        }
    }

    private static boolean autoRestartEnabled(Context context) {
        return Settings.Global.getInt(context.getContentResolver(), AUTO_RESTART_KEY, 0) == 1;
    }

    // Android reports the 120 Hz entry as modeId 1 and 72 Hz as modeId 2, while
    // SurfaceFlinger indexes the same list from zero.
    private static void pinSurfaceFlingerConfig(Context context, int rate) {
        int configIndex = -1;
        DisplayManager manager = (DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE);
        if (manager != null) {
            Display display = manager.getDisplay(Display.DEFAULT_DISPLAY);
            if (display != null) {
                for (Display.Mode mode : display.getSupportedModes()) {
                    if (Math.round(mode.getRefreshRate()) == rate) {
                        configIndex = mode.getModeId() - 1;
                        break;
                    }
                }
            }
        }
        if (configIndex < 0) {
            XposedBridge.log(TAG + ": no SurfaceFlinger config for " + rate + " Hz");
            return;
        }

        android.os.Parcel data = android.os.Parcel.obtain();
        android.os.Parcel reply = android.os.Parcel.obtain();
        try {
            Class<?> surfaceControl = Class.forName("android.view.SurfaceControl");
            for (Method method : surfaceControl.getDeclaredMethods()) {
                String name = method.getName();
                if (name.contains("Config") || name.contains("DisplayToken")
                        || name.contains("PhysicalDisplay")) {
                    XposedBridge.log(TAG + ": SurfaceControl." + name
                            + Arrays.toString(method.getParameterTypes()));
                }
            }

            Object token = null;
            try {
                token = XposedHelpers.callStaticMethod(surfaceControl, "getInternalDisplayToken");
            } catch (Throwable ignored) {
            }
            XposedBridge.log(TAG + ": internalDisplayToken=" + token);
            if (token == null) {
                Object ids = XposedHelpers.callStaticMethod(surfaceControl, "getPhysicalDisplayIds");
                if (ids instanceof long[] && ((long[]) ids).length > 0) {
                    long id = ((long[]) ids)[0];
                    XposedBridge.log(TAG + ": physicalDisplayId=" + id);
                    token = XposedHelpers.callStaticMethod(surfaceControl,
                            "getPhysicalDisplayToken", id);
                }
            }
            if (token == null) {
                XposedBridge.log(TAG + ": no display token available");
                return;
            }

            logDisplayConfigState(surfaceControl, token, "before");
            try {
                XposedHelpers.callStaticMethod(surfaceControl, "setAllowedDisplayConfigs",
                        token, new int[] {configIndex});
                XposedBridge.log(TAG + ": setAllowedDisplayConfigs({" + configIndex + "}) accepted");
            } catch (Throwable error) {
                XposedBridge.log(TAG + ": setAllowedDisplayConfigs failed: " + error);
            }
            try {
                XposedHelpers.callStaticMethod(surfaceControl, "setActiveConfig",
                        token, configIndex);
                XposedBridge.log(TAG + ": setActiveConfig(" + configIndex + ") accepted");
            } catch (Throwable error) {
                XposedBridge.log(TAG + ": setActiveConfig failed: " + error);
            }
            logDisplayConfigState(surfaceControl, token, "after");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": SurfaceFlinger pin failed: " + error);
            XposedBridge.log(error);
        } finally {
            data.recycle();
            reply.recycle();
        }
    }

    // The stock refresh-rate switch only takes effect after the reboot that
    // PicolabFragment.K0() schedules, so the selector has to do the same.
    private static void scheduleRestart(Object fragment) {
        try {
            XposedHelpers.callMethod(fragment, "K0");
            XposedBridge.log(TAG + ": scheduled vendor restart to apply refresh rate");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": restart request failed: " + error);
        }
    }

    private static void dismissPopup(Object fragment) {
        try {
            Class<?> type = fragment.getClass();
            Field popupField = null;
            while (type != null && popupField == null) {
                try {
                    popupField = type.getDeclaredField("g");
                } catch (NoSuchFieldException ignored) {
                    type = type.getSuperclass();
                }
            }
            if (popupField == null) return;
            popupField.setAccessible(true);
            Object popup = popupField.get(fragment);
            if (popup instanceof android.widget.PopupWindow) {
                ((android.widget.PopupWindow) popup).dismiss();
            } else if (popup != null) {
                XposedHelpers.callMethod(popup, "dismiss");
            }
            XposedBridge.log(TAG + ": dismissed refresh popup");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": popup dismissal failed: " + error);
        }
    }

    private static void updateDropdownText(Object fragment, int rate, ClassLoader loader) {
        try {
            Field rootField = fragment.getClass().getDeclaredField("l");
            rootField.setAccessible(true);
            Object root = rootField.get(fragment);
            if (!(root instanceof View)) {
                return;
            }
            View dropdown = ((View) root).findViewById(REFRESH_SWITCH_ID);
            if (dropdown == null) {
                return;
            }
            XposedHelpers.callMethod(dropdown, "setText", rate + " Hz");
        } catch (Throwable error) {
            XposedBridge.log(TAG + ": dropdown label update failed: " + error);
        }
    }

    private static String getProperty(String key, String fallback) {
        try {
            Class<?> properties = Class.forName("android.os.SystemProperties");
            Method get = properties.getMethod("get", String.class, String.class);
            return (String) get.invoke(null, key, fallback);
        } catch (Throwable error) {
            return fallback;
        }
    }
}
