"""Writes icon.ico for the exe (same artwork as the tray icon)."""
from crafts import tray_image

tray_image().save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print("wrote icon.ico")
