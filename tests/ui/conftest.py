import os

# Widget tests draw offscreen: no windows pop up, and CI needs no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
