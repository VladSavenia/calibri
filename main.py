from pathlib import Path

from dlms_browser.gui import DlmsBrowserApp


if __name__ == "__main__":
    app = DlmsBrowserApp(Path("config.json"))
    app.mainloop()
