#ifndef MyAppVersion
  #define MyAppVersion "1.2.0"
#endif
#define MyAppName "Exam Manager"
#define MyAppExeName "GuardApp.exe"

[Setup]
AppId={{B4C92077-41C4-4D31-9C82-AB92B0A0A145}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\GuardApp
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
; اسم ثابت للملف حتى يكون رابط التحميل ثابتاً: .../releases/latest/download/GuardApp-Setup.exe
OutputBaseFilename=GuardApp-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=admin
Uninstallable=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\GuardApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; الأيقونة تُنسخ كملف مستقل ليستخدمها الاختصاران (تتجاوز ذاكرة أيقونات ويندوز القديمة)
Source: "..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; AppUserModelID: "GuardApp.ExamManager"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon; AppUserModelID: "GuardApp.ExamManager"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent
