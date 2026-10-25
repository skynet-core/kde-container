// SPDX-License-Identifier: GPL-2.0-or-later
// KRFB input for the container's KWin virtual monitor, independent of XDP sessions.
#include "events.h"
#include "eventsplugin.h"
#include "fake-input-client.h"

#include <KPluginFactory>
#include <QGuiApplication>
#include <QSocketNotifier>
#include <QDebug>
#include <wayland-client.h>

#include <algorithm>
#include <cstring>

class KwinInput final : public EventHandler
{
public:
    KwinInput()
    {
        m_display = wl_display_connect(nullptr);
        if (!m_display) {
            qFatal("KRFB KWin input: cannot connect to the private Wayland display");
        }
        m_registry = wl_display_get_registry(m_display);
        static const wl_registry_listener listener = {global, globalRemove};
        wl_registry_add_listener(m_registry, &listener, this);
        if (wl_display_roundtrip(m_display) < 0 || !m_input) {
            qFatal("KRFB KWin input: fake-input v6 is unavailable; check KWin and the virtual-monitor desktop permissions");
        }
        org_kde_kwin_fake_input_authenticate(m_input, "Plasma VNC", "Authenticated container VNC session");
        if (wl_display_roundtrip(m_display) < 0) {
            qFatal("KRFB KWin input: authentication roundtrip failed");
        }
        auto notifier = new QSocketNotifier(wl_display_get_fd(m_display), QSocketNotifier::Read, this);
        connect(notifier, &QSocketNotifier::activated, this, [this] {
            if (wl_display_dispatch(m_display) < 0) {
                qFatal("KRFB KWin input: Wayland connection failed");
            }
        });
        qInfo("KRFB KWin input: keyboard, buttons, scrolling and absolute pointer enabled");
    }

    ~KwinInput() override
    {
        // Destroying the device also releases any keys/buttons held by this client.
        org_kde_kwin_fake_input_destroy(m_input);
        wl_registry_destroy(m_registry);
        wl_display_flush(m_display);
        wl_display_disconnect(m_display);
    }

    void handleKeyboard(bool down, rfbKeySym key) override
    {
        org_kde_kwin_fake_input_keyboard_keysym(m_input, key, down ? 1 : 0);
        wl_display_flush(m_display);
    }

    void handlePointer(int buttonMask, int x, int y) override
    {
        org_kde_kwin_fake_input_pointer_motion_absolute(m_input, wl_fixed_from_int(x), wl_fixed_from_int(y));
        // RFB: left, middle, right, wheel up/down/left/right, back, forward.
        static constexpr unsigned buttons[] = {272, 274, 273, 0, 0, 0, 0, 275, 276};
        for (unsigned bit = 0; bit < std::size(buttons); ++bit) {
            const bool down = buttonMask & (1 << bit);
            if (down == bool(m_buttons & (1 << bit))) {
                continue;
            }
            if (buttons[bit]) {
                org_kde_kwin_fake_input_button(m_input, buttons[bit], down ? 1 : 0);
            } else if (down) {
                const int direction = (bit == 3 || bit == 5) ? -15 : 15;
                org_kde_kwin_fake_input_axis(m_input, bit < 5 ? 0 : 1, wl_fixed_from_int(direction));
            }
        }
        m_buttons = buttonMask;
        wl_display_flush(m_display);
    }

private:
    static void global(void *data, wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
    {
        auto self = static_cast<KwinInput *>(data);
        if (std::strcmp(interface, "org_kde_kwin_fake_input") == 0 && version >= 6) {
            self->m_input = static_cast<org_kde_kwin_fake_input *>(
                wl_registry_bind(registry, name, &org_kde_kwin_fake_input_interface, 6));
        }
    }
    static void globalRemove(void *, wl_registry *, uint32_t) {}
    wl_display *m_display = nullptr;
    wl_registry *m_registry = nullptr;
    org_kde_kwin_fake_input *m_input = nullptr;
    int m_buttons = 0;
};

class KwinEventsPlugin final : public EventsPlugin
{
    Q_OBJECT
public:
    KwinEventsPlugin(QObject *parent, const QVariantList &args) : EventsPlugin(parent, args) {}
    EventHandler *eventHandler() override
    {
        if (qEnvironmentVariableIntValue("PLASMA_KWIN_INPUT") != 1 || QGuiApplication::platformName() != "wayland") {
            return nullptr;
        }
        return new KwinInput;
    }
};

K_PLUGIN_CLASS(KwinEventsPlugin)
#include "kwin-input.moc"
