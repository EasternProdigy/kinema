' Kinema launcher for Windows that runs without a console window.
' Double-click this instead of Kinema.bat if you don't want a black terminal.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
batch = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "Kinema.bat")
sh.Run """" & batch & """", 0, False
