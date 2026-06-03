Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\18187\Documents\WinWhisper"
WshShell.Run "pythonw ""C:\Users\18187\Documents\WinWhisper\winwhisper.py""", 0, False
