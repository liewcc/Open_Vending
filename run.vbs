Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(scriptDir & "\node_modules\.bin\electron.cmd") Then
    MsgBox "Setup not complete. Please run setup.bat first.", 16, "Open Vending"
    WScript.Quit
End If

WshShell.CurrentDirectory = scriptDir
WshShell.Run "cmd.exe /c run.bat", 0, False
