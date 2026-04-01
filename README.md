# DLMS/COSEM Browser (Gurux-based)

A small Python desktop utility for browsing a DLMS/COSEM meter object tree over a serial HDLC connection.

## Features

- serial/COM port selection
- basic DLMS/HDLC connection settings
- connect / disconnect buttons
- read association view on demand
- tree view grouped by object class
- attribute readout when an object node is selected
- JSON config file
- simple Tkinter GUI

## Dependencies

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Notes

This project is intentionally focused on the most common serial HDLC use case.
If your meter requires security suite, invocation counter handling, optical head Mode E initialization, or vendor-specific behavior, extend `dlms_browser/dlms_service.py` using the original Gurux example sources.

## License note

The original Gurux repository is GPL-2.0 licensed. If you continue developing this project by reusing or adapting Gurux example code, keep the license implications in mind.
