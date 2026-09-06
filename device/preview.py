"""RAM-only display preview. Reset the Stick to return to UiFlow2.

Button A: older lines. Button B: newer lines.
Hold either button to repeat. No audio is recorded in this preview.
"""
import time
import M5

# TextView is prepended by scripts/preview.py before this script is sent.
M5.begin()
M5.Speaker.end()
M5.Lcd.setRotation(1)
M5.Lcd.setBrightness(90)
M5.Lcd.setTextSize(1)
M5.Lcd.setFont(M5.Lcd.FONTS.DejaVu12)
view = TextView(M5.Lcd)
view.append("Pocket Hermes display preview\n")
view.append("Hold to talk will send speech to your esp32 profile. Replies will appear here as short, scrollable text.\n")
view.append("The display keeps earlier lines so you can read at your own pace. Long answers can still be explored.\n")
view.append("This is sample text, not a live Hermes response.\n")
view.append("A: scroll up\nB: scroll down\nReset: return to UiFlow")
view.top = 0
view.follow = False
view.status = "Preview / A up  B down"
view.draw()
print("PREVIEW_READY", M5.Lcd.width(), M5.Lcd.height(), len(view.lines))
last_repeat = time.ticks_ms()
while True:
    M5.update()
    now = time.ticks_ms()
    step = 0
    if M5.BtnA.wasPressed():
        step = -1
    elif M5.BtnB.wasPressed():
        step = 1
    elif time.ticks_diff(now, last_repeat) > 180:
        if M5.BtnA.pressedFor(500):
            step = -1
        elif M5.BtnB.pressedFor(500):
            step = 1
    if step:
        last_repeat = now
        view.scroll(step)
        view.draw()
        print("SCROLL", view.top)
    time.sleep_ms(20)
