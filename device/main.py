# Pocket Hermes entry point. Hold B during startup to return to UiFlow2.
import time
import M5
M5.begin()
time.sleep_ms(200)
M5.update()
if M5.BtnB.isPressed():
    import esp32
    import machine
    nvs = esp32.NVS('uiflow')
    nvs.set_u8('boot_option', 1)
    nvs.commit()
    machine.reset()
else:
    from pocket import run
    run()
