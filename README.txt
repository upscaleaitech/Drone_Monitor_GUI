Drone Monitor GUI
└─ GUI/
   ├─ main.py                      # entry point (arg parsing, window setup)
   ├─ gui_mainwindow.py            # UI + map (Leaflet in QWebEngine)
   ├─ serial_location_reader.py    # serial thread, decode & signals
   └─ assets/
      ├─ company_logo.svg|png      # company logo (optional)
      └─ (icons, future images)
•	Python version : 3.9–3.12 recommended
•	Run Commands:
		py -m pip install --user -r requirements.txt
		python main.py --port COM7 --baud 115200 --logfile uart.txt --binfile cap.bin --hexdump cap.hex --hexwidth 32 --web-map on
•	Log characters:
		example: seq":1,"ts_ms":239,"lat":17.385000,"lon":78.486702,"altitude":0.00,"mode":0,"armed":false,"battery_voltage":16.05,"remain_min":18.1,"gps_sats":10,"gps_fix":3,"pitch":0.00,"roll":0.00,"yaw":0.00,"vx":0.00,"vy":0.00,"vz":0.00}
 
•	Here Command Line Arguments
       Flag	        Type	Default	  Description
       --port	    str	    required  Serial COM port (e.g., COM7).
       --baud	    int	    115200	  Serial baud rate.
       --logfile	path	(none)	  Append decoded text log to this file.
       --binfile	path	(none)	  Save raw binary capture stream.
       --hexdump	path	(none)	  Write a running hex dump file.
       --hexwidth	int	    32	     Bytes per line for hex dump.
       --web-map	enum	auto	 on = use online tiles; off = show offline panel; auto = try online.
