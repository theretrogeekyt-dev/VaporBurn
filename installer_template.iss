; ==============================================================================
; VaporBurn - Automated Inno Setup Installer Script
; Companion installer for VaporFetch game backups with Goldberg emulator
; ==============================================================================

#ifndef GameName
  #define GameName "Game"
#endif

#ifndef AppVersion
  #define AppVersion "1.0"
#endif

#ifndef AppPublisher
  #define AppPublisher "VaporFetch / VaporBurn"
#endif

#ifndef AppExe
  #define AppExe "Game.exe"
#endif

#ifndef AppExeDir
  #define AppExeDir ""
#endif

#ifndef AppId
  #define AppId "480"
#endif

#ifndef SourceDir
  #define SourceDir "staging"
#endif

#ifndef OutputDir
  #define OutputDir "output"
#endif

#ifndef OutputBaseName
  #define OutputBaseName "setup"
#endif

#ifndef ChunkSize
  ; Default chunk size 4GB (FAT32 compatible)
  #define ChunkSize "4294967295"
#endif

#ifndef HasDirectX
  #define HasDirectX "0"
#endif
#ifndef DirectXExe
  #define DirectXExe ""
#endif

#ifndef HasVCRedist64
  #define HasVCRedist64 "0"
#endif
#ifndef VCRedist64Exe
  #define VCRedist64Exe ""
#endif

#ifndef HasVCRedist86
  #define HasVCRedist86 "0"
#endif
#ifndef VCRedist86Exe
  #define VCRedist86Exe ""
#endif

#ifndef HasSaves
  #define HasSaves "0"
#endif
#ifndef SavesRelDir
  #define SavesRelDir ""
#endif

[Setup]
; Basic Application Info
AppId={{#GameName}-{#AppId}-VAPORBURN}
AppName={#GameName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#GameName}
DefaultGroupName={#GameName}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}

; Compression & Disk Spanning Configuration
Compression=lzma2/ultra64
InternalCompressLevel=ultra
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=2
DiskSpanning=yes
DiskSliceSize={#ChunkSize}
SlicesPerDisk=1

; Modern UI Appearance
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=yes
AllowNoIcons=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#GameName} (Uninstall)

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "firewall"; Description: "Configure Windows Firewall rule (Recommended for LAN & P2P multiplayer)"; GroupDescription: "Network Integration:"

#if HasDirectX == "1"
Name: "redist_dx"; Description: "Install DirectX End-User Runtimes (Silent)"; GroupDescription: "Prerequisites & Dependencies:"
#endif

#if HasVCRedist64 == "1"
Name: "redist_vc64"; Description: "Install Visual C++ 64-bit Redistributable"; GroupDescription: "Prerequisites & Dependencies:"
#endif

#if HasVCRedist86 == "1"
Name: "redist_vc86"; Description: "Install Visual C++ 32-bit Redistributable"; GroupDescription: "Prerequisites & Dependencies:"
#endif

#if HasSaves == "1"
Name: "restoresaves"; Description: "Restore bundled Goldberg save data to %APPDATA%"; GroupDescription: "Save Data Management:"
#endif

[Files]
; Main game data files
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#GameName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}\{#AppExeDir}"
Name: "{group}\{cm:UninstallProgram,{#GameName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#GameName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}\{#AppExeDir}"; Tasks: desktopicon

[Run]
; Firewall Rule
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#GameName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes"; Flags: runhidden; Tasks: firewall
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#GameName}"" dir=out action=allow program=""{app}\{#AppExe}"" enable=yes"; Flags: runhidden; Tasks: firewall

; Redistributables execution
#if HasDirectX == "1"
Filename: "{app}\{#DirectXExe}"; Parameters: "/silent"; StatusMsg: "Installing DirectX Runtimes..."; Flags: runhidden; Tasks: redist_dx
#endif

#if HasVCRedist64 == "1"
Filename: "{app}\{#VCRedist64Exe}"; Parameters: "/install /passive /norestart"; StatusMsg: "Installing Visual C++ (x64)..."; Flags: runhidden; Tasks: redist_vc64
#endif

#if HasVCRedist86 == "1"
Filename: "{app}\{#VCRedist86Exe}"; Parameters: "/install /passive /norestart"; StatusMsg: "Installing Visual C++ (x86)..."; Flags: runhidden; Tasks: redist_vc86
#endif

; Post-install launch & integrity check options
Filename: "{app}\verify_integrity.bat"; Description: "Verify installed file integrity (SHA-256 Checksums)"; Flags: postinstall skipifsilent nowait unchecked
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(GameName, '&', '&&')}}"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
; Remove Firewall Rule on Uninstall
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#GameName}"""; Flags: runhidden

[UninstallDelete]
; Clean up generated steam_settings and logs, but preserve player saves
Type: files; Name: "{app}\steam_settings\*.txt"
Type: files; Name: "{app}\steam_settings\*.ini"
Type: dirifempty; Name: "{app}\steam_settings"
Type: files; Name: "{app}\verify_integrity.bat"
Type: files; Name: "{app}\checksums.sha256"
Type: files; Name: "{app}\integrity_verification.log"

[Code]
// ==============================================================================
// Win32 API Imports for Memory Management & Hardware Checking
// ==============================================================================
type
  TMemoryStatusEx = record
    dwLength: DWORD;
    dwMemoryLoad: DWORD;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var lpBuffer: TMemoryStatusEx): BOOL;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';

function SetProcessWorkingSetSize(hProcess: THandle; dwMinimumWorkingSetSize, dwMaximumWorkingSetSize: Cardinal): BOOL;
  external 'SetProcessWorkingSetSize@kernel32.dll stdcall';

function SetPriorityClass(hProcess: THandle; dwPriorityClass: DWORD): BOOL;
  external 'SetPriorityClass@kernel32.dll stdcall';

// ==============================================================================
// Global Variables
// ==============================================================================
var
  RAMLimitCheckBox: TCheckBox;
  GoldbergPage: TInputQueryWizardPage;
  NetworkOptionPage: TInputOptionWizardPage;
  IsLowRAMDetected: Boolean;

// ==============================================================================
// Helper Functions: File Writing & Directory Scanning
// ==============================================================================
procedure WriteStringToFile(FilePath, Content: String);
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := Content;
  SaveStringsToUTF8File(FilePath, Lines, False);
end;

procedure CopyDirectory(SourcePath, DestPath: String);
var
  FindRec: TFindRec;
  SrcItem, DstItem: String;
begin
  ForceDirectories(DestPath);
  if FindFirst(SourcePath + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          SrcItem := SourcePath + '\' + FindRec.Name;
          DstItem := DestPath + '\' + FindRec.Name;
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            CopyDirectory(SrcItem, DstItem)
          else
            FileCopy(SrcItem, DstItem, False);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// Recursively locate all steam_api*.dll parent folders to configure steam_settings
procedure ConfigureGoldbergInFolder(BaseDir, PlayerName, Language, SteamId: String; OfflineMode: Boolean);
var
  FindRec: TFindRec;
  SubDir, SettingsDir: String;
  HasSteamApi: Boolean;
begin
  HasSteamApi := FileExists(BaseDir + '\steam_api.dll') or FileExists(BaseDir + '\steam_api64.dll');
  
  if HasSteamApi then
  begin
    SettingsDir := BaseDir + '\steam_settings';
    ForceDirectories(SettingsDir);
    WriteStringToFile(SettingsDir + '\force_account_name.txt', PlayerName);
    WriteStringToFile(SettingsDir + '\force_language.txt', Language);
    WriteStringToFile(SettingsDir + '\force_steamid.txt', SteamId);
    
    if OfflineMode then
      WriteStringToFile(SettingsDir + '\offline.txt', '1')
    else if FileExists(SettingsDir + '\offline.txt') then
      DeleteFile(SettingsDir + '\offline.txt');

    // Ensure steam_appid.txt exists next to the DLL
    if not FileExists(BaseDir + '\steam_appid.txt') then
      WriteStringToFile(BaseDir + '\steam_appid.txt', '{#AppId}');
  end;

  // Recurse into subdirectories
  if FindFirst(BaseDir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) then
        begin
          SubDir := BaseDir + '\' + FindRec.Name;
          // Skip redists, logs, and steam_settings themselves
          if (FindRec.Name <> 'steam_settings') and (FindRec.Name <> '_CommonRedist') and (FindRec.Name <> 'Redistributables') then
            ConfigureGoldbergInFolder(SubDir, PlayerName, Language, SteamId, OfflineMode);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// Creates a standalone batch verifier in {app}\verify_integrity.bat
procedure GenerateVerificationBatch(AppPath: String);
var
  BatContent: String;
  BatPath: String;
begin
  BatPath := AppPath + '\verify_integrity.bat';
  BatContent :=
    '@echo off' + #13#10 +
    'title VaporBurn SHA-256 Integrity Verifier' + #13#10 +
    'cd /d "%~dp0"' + #13#10 +
    'echo ======================================================' + #13#10 +
    'echo       VaporBurn File Integrity Verification' + #13#10 +
    'echo ======================================================' + #13#10 +
    'echo Verifying files against checksums.sha256...' + #13#10 +
    'setlocal enabledelayedexpansion' + #13#10 +
    'set /a total=0' + #13#10 +
    'set /a matched=0' + #13#10 +
    'set /a failed=0' + #13#10 +
    'if not exist checksums.sha256 (' + #13#10 +
    '    echo [ERROR] checksums.sha256 not found in game directory.' + #13#10 +
    '    pause' + #13#10 +
    '    exit /b 1' + #13#10 +
    ')' + #13#10 +
    'for /f "tokens=1* delims=*" %%A in (checksums.sha256) do (' + #13#10 +
    '    set /a total+=1' + #13#10 +
    '    set "EXP_HASH=%%A"' + #13#10 +
    '    set "EXP_HASH=!EXP_HASH: =!"' + #13#10 +
    '    set "REL_FILE=%%B"' + #13#10 +
    '    if not exist "!REL_FILE!" (' + #13#10 +
    '        echo [MISSING] !REL_FILE!' + #13#10 +
    '        set /a failed+=1' + #13#10 +
    '    ) else (' + #13#10 +
    '        for /f "skip=1 delims=" %%H in (''certutil -hashfile "!REL_FILE!" SHA256 2^>nul'') do (' + #13#10 +
    '            if not defined CUR_HASH (' + #13#10 +
    '                set "CUR_HASH=%%H"' + #13#10 +
    '                set "CUR_HASH=!CUR_HASH: =!"' + #13#10 +
    '            )' + #13#10 +
    '        )' + #13#10 +
    '        if /i "!CUR_HASH!"=="!EXP_HASH!" (' + #13#10 +
    '            echo [OK] !REL_FILE!' + #13#10 +
    '            set /a matched+=1' + #13#10 +
    '        ) else (' + #13#10 +
    '            echo [MISMATCH] !REL_FILE!' + #13#10 +
    '            set /a failed+=1' + #13#10 +
    '        )' + #13#10 +
    '        set "CUR_HASH="' + #13#10 +
    '    )' + #13#10 +
    ')' + #13#10 +
    'echo.' + #13#10 +
    'echo ------------------------------------------------------' + #13#10 +
    'echo Total Files: !total!' + #13#10 +
    'echo Matched:     !matched!' + #13#10 +
    'echo Failed:      !failed!' + #13#10 +
    'echo ------------------------------------------------------' + #13#10 +
    'if !failed! EQU 0 (' + #13#10 +
    '    echo ALL FILES VERIFIED SUCCESSFULLY! No corruption detected.' + #13#10 +
    ') else (' + #13#10 +
    '    echo [WARNING] Some files failed verification or are missing!' + #13#10 +
    ')' + #13#10 +
    'pause' + #13#10;

  WriteStringToFile(BatPath, BatContent);
end;

// ==============================================================================
// Wizard Initialization & Custom UI Construction
// ==============================================================================
function InitializeSetup(): Boolean;
var
  MemStatus: TMemoryStatusEx;
begin
  Result := True;
  IsLowRAMDetected := False;

  // Query System Physical RAM
  MemStatus.dwLength := SizeOf(MemStatus);
  if GlobalMemoryStatusEx(MemStatus) then
  begin
    // Check if total physical RAM is <= 8GB (8 * 1024 * 1024 * 1024 = 8589934592 bytes)
    if MemStatus.ullTotalPhys <= 8589934592 then
      IsLowRAMDetected := True;
  end;
end;

procedure InitializeWizard();
begin
  // 1. RAM Limiter Checkbox on Welcome Page
  RAMLimitCheckBox := TCheckBox.Create(WizardForm);
  RAMLimitCheckBox.Parent := WizardForm.WelcomePage;
  RAMLimitCheckBox.Left := ScaleX(180);
  RAMLimitCheckBox.Top := ScaleY(265);
  RAMLimitCheckBox.Width := ScaleX(315);
  RAMLimitCheckBox.Height := ScaleY(30);
  RAMLimitCheckBox.Caption := 'Limit installer RAM usage to 2GB (Recommended for <= 8GB RAM)';
  RAMLimitCheckBox.Hint := 'Restricts decompression memory footprint to prevent out-of-memory crashes on low-spec systems.';
  RAMLimitCheckBox.ShowHint := True;
  RAMLimitCheckBox.Checked := IsLowRAMDetected;

  // 2. Goldberg Configuration Wizard Page
  GoldbergPage := CreateInputQueryPage(
    wpSelectDir,
    'Goldberg Steam Profile Configuration',
    'Configure your offline player identity and settings',
    'VaporBurn integrates Goldberg Steam Emulator for DRM-free offline play.' + #13#10 +
    'Specify your profile details below (saved to steam_settings):'
  );
  GoldbergPage.Add('Player Name (Steam Username):', False);
  GoldbergPage.Add('Language (e.g. english, german, french, spanish, russian):', False);
  GoldbergPage.Add('Steam ID64 (Custom 17-digit ID, or leave default):', False);

  // Default values
  GoldbergPage.Values[0] := 'VaporPlayer';
  GoldbergPage.Values[1] := 'english';
  GoldbergPage.Values[2] := '76561197960287930';

  // 3. Goldberg Networking Mode Page
  NetworkOptionPage := CreateInputOptionPage(
    GoldbergPage.ID,
    'Goldberg Networking & Multiplayer Options',
    'Configure LAN play and Steam socket emulation',
    'Choose network visibility for this game install:',
    True, False
  );
  NetworkOptionPage.Add('Enable Local Network (LAN) & Steam P2P Multiplayer (Default)');
  NetworkOptionPage.Add('Enforce Pure Offline Mode (Disable all socket networking)');
  NetworkOptionPage.SelectedValueIndex := 0;
end;

// ==============================================================================
// Step Change Event Handlers
// ==============================================================================
procedure CurStepChanged(CurStep: TSetupStep);
var
  PlayerName, Language, SteamId, SaveSrc, SaveDst: String;
  OfflineMode: Boolean;
  TotalPhysRAM: Int64;
begin
  if CurStep = ssInstall then
  begin
    // Apply RAM Limiter if requested
    if RAMLimitCheckBox.Checked then
    begin
      // Limit process working set to 64MB min, 2048MB (2GB) max
      SetProcessWorkingSetSize(THandle(-1), 67108864, 2147483648);
      // Set below normal priority to ensure OS stability during high decompression load
      SetPriorityClass(THandle(-1), $00004000); // BELOW_NORMAL_PRIORITY_CLASS
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    // 1. Configure Goldberg Settings
    PlayerName := Trim(GoldbergPage.Values[0]);
    if PlayerName = '' then PlayerName := 'VaporPlayer';

    Language := LowerCase(Trim(GoldbergPage.Values[1]));
    if Language = '' then Language := 'english';

    SteamId := Trim(GoldbergPage.Values[2]);
    if SteamId = '' then SteamId := '76561197960287930';

    OfflineMode := (NetworkOptionPage.SelectedValueIndex = 1);

    ConfigureGoldbergInFolder(ExpandConstant('{app}'), PlayerName, Language, SteamId, OfflineMode);

    // 2. Restore bundled save files if requested
    #if HasSaves == "1"
    if WizardIsTaskSelected('restoresaves') then
    begin
      SaveSrc := ExpandConstant('{app}\{#SavesRelDir}');
      SaveDst := ExpandConstant('{userappdata}\Goldberg SteamEmu Saves\' + SteamId + '\{#AppId}');
      if DirExists(SaveSrc) then
      begin
        CopyDirectory(SaveSrc, SaveDst);
      end;
    end;
    #endif

    // 3. Generate SHA-256 verification batch script
    GenerateVerificationBatch(ExpandConstant('{app}'));
  end;
end;
