; ABOUT
; NSIS script file for Artisan Windows installer.
;
; LICENSE
; This program or module is free software: you can redistribute it and/or
; modify it under the terms of the GNU General Public License as published
; by the Free Software Foundation, either version 2 of the License, or
; version 3 of the License, or (at your option) any later versison. It is
; provided for educational purposes and is distributed in the hope that
; it will be useful, but WITHOUT ANY WARRANTY; without even the implied
; warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
; the GNU General Public License for more details.
;
; AUTHOR
; Dave Baxter, Marko Luther 2023
;
; .nsi command line options:
;    /DPRODUCT_VERSION=ww.xx.yy     -explicitly set the product version, default is 0.0.0
;    /DPRODUCT_BUILD=zz             -explicityl set the product build, default is 0
;    /DLEGACY=True|False            -True is a build for legacy Windows, default is False
;    /DSIGN=True|False              -True if the build is part of the process to sign files, default is False
;                                    Note: SignArtisan is not a part of the ci process
;
; installer command line options
;    /S                             -silent operation

; Tilauscope NSIS script file for Artisan Windows installer.
;

RequestExecutionLevel admin
Unicode true

!macro APP_ASSOCIATE_URL FILECLASS DESCRIPTION COMMANDTEXT COMMAND
  WriteRegStr HKCR "${FILECLASS}" "" `${DESCRIPTION}`
  WriteRegStr HKCR "${FILECLASS}" "URL Protocol" ""
  WriteRegStr HKCR "${FILECLASS}\shell" "" "open"
  WriteRegStr HKCR "${FILECLASS}\shell\open" "" `${COMMANDTEXT}`
  WriteRegStr HKCR "${FILECLASS}\shell\open\command" "" `${COMMAND}`
!macroend

!macro APP_ASSOCIATE EXT FILECLASS DESCRIPTION ICON COMMANDTEXT COMMAND
  ; Backup the previously associated file class
  ReadRegStr $R0 HKCR ".${EXT}" ""
  WriteRegStr HKCR ".${EXT}" "${FILECLASS}_backup" "$R0"
  WriteRegStr HKCR ".${EXT}" "" "${FILECLASS}"
  WriteRegStr HKCR "${FILECLASS}" "" `${DESCRIPTION}`
  WriteRegStr HKCR "${FILECLASS}\DefaultIcon" "" `${ICON}`
  WriteRegStr HKCR "${FILECLASS}\shell" "" "open"
  WriteRegStr HKCR "${FILECLASS}\shell\open" "" `${COMMANDTEXT}`
  WriteRegStr HKCR "${FILECLASS}\shell\open\command" "" `${COMMAND}`
!macroend

!macro APP_UNASSOCIATE EXT FILECLASS
  ; Backup the previously associated file class
  ReadRegStr $R0 HKCR ".${EXT}" `${FILECLASS}_backup`
  WriteRegStr HKCR ".${EXT}" "" "$R0"
  DeleteRegKey HKCR `${FILECLASS}`
!macroend

!macro Rmdir_Wildcard dir uid
  ; RMDIR with wildcard, dir in the form $INSTDIR\dir_with_wildcard, uid should be ${__LINE__}
  FindFirst $0 $1 ${dir}
  loop_${uid}:
    StrCmp $1 "" endloop_${uid}
    RMDIR /r "$INSTDIR\$1"
    FindNext $0 $1
    Goto loop_${uid}
  endloop_${uid}:
  FindClose $0
!macroend

!macro IsRunning MUTEX_NAME
    System::Call 'kernel32::OpenMutex(i 0x00100000, i 0, t "${MUTEX_NAME}") i .r0'
    IntCmp $r0 0 notRunning
        System::Call 'kernel32::CloseHandle(i $r0)'
        MessageBox MB_ICONSTOP "$(DESC_AlreadyRunning)"
        Abort
    notRunning:
!macroend

; --- CONFIGURATION MUI ---
!include "MUI2.nsh" ; Interface moderne
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

; Active la détection automatique de la langue du système [cite: 24]
!define MUI_LANGDLL_ALWAYSDETECT 

; Pages de l'installeur [cite: 24]
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Page du désinstalleur [cite: 25]
!insertmacro MUI_UNPAGE_INSTFILES

!define PRODUCT_NAME "artisan"

; --- LANGUES ET TRADUCTIONS ---
; L'anglais est défini en premier comme langue par défaut (fallback) [cite: 25]
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"
LangString DESC_AdminRequired ${LANG_ENGLISH} "Administrative privileges are required to install ${PRODUCT_NAME}.$\nPlease restart the installer as an administrator."
LangString DESC_AdminRequired ${LANG_FRENCH} "Des privilèges d'administrateur sont requis pour installer ${PRODUCT_NAME}.$\nVeuillez relancer l'installeur en tant qu'administrateur."

LangString DESC_AlreadyRunning ${LANG_ENGLISH} "${PRODUCT_NAME} is already running, please exit the application before upgrading or uninstalling."
LangString DESC_AlreadyRunning ${LANG_FRENCH} "${PRODUCT_NAME} est déjà en cours d'exécution. Veuillez quitter l'application avant la mise à jour ou la désinstallation."

LangString DESC_AlreadyInstalled ${LANG_ENGLISH} "${PRODUCT_NAME} is already installed. $\n$\nClick `OK` to remove the previous version or `Cancel` to cancel this upgrade."
LangString DESC_AlreadyInstalled ${LANG_FRENCH} "${PRODUCT_NAME} est déjà installé. $\n$\nCliquez sur `OK` pour supprimer la version précédente ou sur `Annuler` pour abandonner la mise à jour."

LangString DESC_64bitOnly ${LANG_ENGLISH} "This is a 64-bit application. Your system is not 64-bit compatible."
LangString DESC_64bitOnly ${LANG_FRENCH} "Ceci est une application 64-bit. Votre système n'est pas compatible 64-bit."

LangString DESC_UninstError ${LANG_ENGLISH} "Previous version could not be fully removed."
LangString DESC_UninstError ${LANG_FRENCH} "La version précédente n'a pas pu être totalement supprimée."

LangString DESC_UninstConfirm ${LANG_ENGLISH} "Are you sure you want to remove $(^Name)?"
LangString DESC_UninstConfirm ${LANG_FRENCH} "Êtes-vous sûr de vouloir supprimer $(^Name) ?"

LangString DESC_UninstSuccess ${LANG_ENGLISH} "$(^Name) was successfully removed from your computer."
LangString DESC_UninstSuccess ${LANG_FRENCH} "$(^Name) a été supprimé avec succès de votre ordinateur."

LangString DESC_PreviouslyNotRemoved ${LANG_ENGLISH} "Previous version could not be fully removed."
LangString DESC_PreviouslyNotRemoved ${LANG_FRENCH} "La version précédente n'a pas pu être totalement supprimée."

LangString DESC_OpenWith ${LANG_ENGLISH} "Open with ${PRODUCT_NAME}"
LangString DESC_OpenWith ${LANG_FRENCH} "Ouvrir avec ${PRODUCT_NAME}"

LangString DESC_OpenWithURL ${LANG_ENGLISH} "Open with URL"
LangString DESC_OpenWithURL ${LANG_FRENCH} "Ouvrir avec URL"


; HM NIS Edit Wizard helper defines
!define pyinstallerOutputDir 'dist/artisan'
!define PRODUCT_PUBLISHER "Tilau"
!define PRODUCT_WEB_SITE "https://github.com/artisan/README.md"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\artisan.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"

; Special commandline options
; Product version and build can be defined on the command line '/DPRODUCT_VERSION=ww.xx.yy'
;   and '/DPRODUCT_VERSION=zz' These will override the default version an build explicitly set below.
!define /ifndef PRODUCT_VERSION "0.0.0"
!define /ifndef PRODUCT_BUILD "0"
!define /ifndef SIGN "False"

!define /date CUR_YEAR "%Y"
Caption "${PRODUCT_NAME} Installer"

VIProductVersion "${PRODUCT_VERSION}.${PRODUCT_BUILD}"
VIAddVersionKey ProductName "${PRODUCT_NAME}"
VIAddVersionKey Comments "Installer for artisan"
VIAddVersionKey CompanyName ""
VIAddVersionKey LegalCopyright "Copyright 2025-${CUR_YEAR}, Tilau. GNU General Public License"
VIAddVersionKey FileVersion "${PRODUCT_VERSION}.${PRODUCT_BUILD}"
VIAddVersionKey FileDescription "${PRODUCT_NAME} Installer"
VIAddVersionKey ProductVersion "${PRODUCT_VERSION}.${PRODUCT_BUILD}"

; MUI Settings
!define MUI_ABORTWARNING
;!define MUI_ICON "artisan.ico"
;!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; MUI end ------

Name "${PRODUCT_NAME}"
OutFile "artisan-win-x64-${PRODUCT_VERSION}-setup.exe"
InstallDir "$PROGRAMFILES64\artisan"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
ShowInstDetails show
ShowUnInstDetails show

Function .onInit

; 2. Vérification des droits Administrateur
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 != "Admin"
    MessageBox MB_OK|MB_ICONSTOP "$(DESC_AdminRequired)"
    Abort
  ${EndIf}

;  3. Vérification si l'application est déjà en cours d'exécution
  !insertmacro IsRunning "Global\artisan_Mutex"

; 4. Vérification de l'architecture 64-bit [cite: 32, 33]
  ${If} ${RunningX64}
    ; Vérification d'une installation existante pour mise à jour/désinstallation [cite: 31]
    ReadRegStr $R0 ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString"
    StrCmp $R0 "" done

    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(DESC_AlreadyInstalled)" /SD IDOK IDOK uninst
    Abort
  ${Else}
    MessageBox MB_OK "$(DESC_64bitOnly)"
    Abort
  ${EndIf}

; 5. Exécution du désinstalleur de la version précédente
  uninst:
    ClearErrors
    IfSilent mysilent nosilent
  
  mysilent:
    ; Exécution silencieuse sans copier le désinstalleur en dossier temporaire [cite: 33]
    ExecWait '$R0 /S _?=$INSTDIR'
    IfErrors no_remove_uninstaller done

  nosilent:
    ; Exécution normale [cite: 33]
    ExecWait '$R0 _?=$INSTDIR'
    IfErrors no_remove_uninstaller done
  
  no_remove_uninstaller:
    ; Optionnel : Message si la désinstallation automatique a échoué
    DetailPrint "$(DESC_PreviouslyNotRemoved)"

  done:
FunctionEnd

Section "MainSection" SEC01
  SetShellVarContext all
  SetOutPath "$INSTDIR"
  SetOverwrite ifnewer
  File /r '${pyinstallerOutputDir}\*.*'
  CreateDirectory "$SMPROGRAMS\artisan"
  CreateShortCut "$SMPROGRAMS\artisan\artisan.lnk" "$INSTDIR\artisan.exe"
  CreateShortCut "$DESKTOP\artisan.lnk" "$INSTDIR\artisan.exe"
SectionEnd

Section "Microsoft Visual C++ Redistributable Package (x64)" SEC02
  ExecWait '$INSTDIR\vc_redist.x64.exe /install /passive /norestart'
  Delete '$INSTDIR\vc_redist.x64.exe'
SectionEnd

Section -AdditionalIcons
  SetShellVarContext all
  WriteIniStr "$INSTDIR\${PRODUCT_NAME}.url" "InternetShortcut" "URL" "${PRODUCT_WEB_SITE}"
  CreateShortCut "$SMPROGRAMS\artisan\Website.lnk" "$INSTDIR\${PRODUCT_NAME}.url"
  CreateShortCut "$SMPROGRAMS\artisan\Uninstall.lnk" "$INSTDIR\uninst.exe"
SectionEnd

Section -Post
  ;The generated uninst.exe file needs to be redirected when signing so the signed uninstaller is packed. Include '/DSign="True"' on the command line.
  !if ${Sign} S== "True"
    WriteUninstaller "$%TEMP%\uninst.exe"
  !else
    WriteUninstaller "$INSTDIR\uninst.exe"
  !endif

  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\artisan.exe"
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "Path" "$INSTDIR"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\artisan.exe"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}.${PRODUCT_BUILD}"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
  WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"

  ; file associations
  !insertmacro APP_ASSOCIATE "alog" "Artisan.Profile" "Artisan Roast Profile" \
     "$INSTDIR\artisanProfile.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE "alrm" "Artisan.Alarms" "Artisan Alarms" \
     "$INSTDIR\artisanAlarms.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE "apal" "Artisan.Palettes" "Artisan Palettes" \
     "$INSTDIR\artisanPalettes.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE "athm" "Artisan.Theme" "Artisan Theme" \
     "$INSTDIR\artisanTheme.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE "aset" "Artisan.Settings" "Artisan Settings" \
     "$INSTDIR\artisanSettings.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE "wg" "Artisan.Wheel" "Artisan Wheel" \
     "$INSTDIR\artisanWheel.ico" "$(DESC_OpenWith)" "$INSTDIR\artisan.exe $\"%1$\""

  !insertmacro APP_ASSOCIATE_URL "artisan" "URL:artisan Protocol" \
     "$(DESC_OpenWithURL)" "$INSTDIR\artisan.exe $\"%1$\""

SectionEnd

Function un.onUninstSuccess
  HideWindow
  IfSilent +2 0
    MessageBox MB_ICONINFORMATION|MB_OK "$(DESC_UninstSuccess)" /SD IDOK
FunctionEnd

Function un.onInit
    !insertmacro IsRunning "Global\artisan_Mutex"

    IfSilent +3
        MessageBox MB_ICONQUESTION|MB_YESNO|MB_TOPMOST "$(DESC_UninstConfirm)" IDYES +2
        Abort
    HideWindow
FunctionEnd

Section Uninstall
  ; 1. Suppression des fichiers principaux
  Delete "$INSTDIR\${PRODUCT_NAME}.url"
  Delete "$INSTDIR\uninst.exe"
  Delete "$INSTDIR\artisan.exe"
  Delete "$INSTDIR\artisan.exe.manifest"
  Delete "$INSTDIR\base_library.zip"
  Delete "$INSTDIR\logging.yaml"
  
  ; Suppression des fichiers binaires par joker pour plus de flexibilité
  Delete "$INSTDIR\*.pyd"
  Delete "$INSTDIR\*.dll"

  ; 2. Suppression des répertoires de dépendances (Nettoyage groupé)
  ; On utilise /r avec prudence sur les dossiers spécifiques à l'app
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\translations"
  RMDir /r "$INSTDIR\Icons"
  RMDir /r "$INSTDIR\Themes"
  RMDir /r /REBOOTOK "$INSTDIR"

  ; Utilisation de la macro wildcard pour les dossiers PyQt et Qt (très variables)
  !insertmacro Rmdir_Wildcard "$INSTDIR\PyQt*" ${__LINE__}
  !insertmacro Rmdir_Wildcard "$INSTDIR\qt*" ${__LINE__}
  !insertmacro Rmdir_Wildcard "$INSTDIR\*.dist-info" ${__LINE__}
  !insertmacro Rmdir_Wildcard "$INSTDIR\*.egg-info" ${__LINE__}

  ; 3. Nettoyage des ressources et polices
  Delete "$INSTDIR\*.ttf"
  Delete "$INSTDIR\*.otf"
  Delete "$INSTDIR\*.woff*"
  Delete "$INSTDIR\*.png"
  Delete "$INSTDIR\*.ico"

  ; 4. Suppression des raccourcis (All Users)
  SetShellVarContext all
  Delete "$SMPROGRAMS\artisan\Uninstall.lnk"
  Delete "$SMPROGRAMS\artisan\artisan.lnk"
  Delete "$DESKTOP\artisan.lnk"
  RMDir "$SMPROGRAMS\artisan"

  ; 5. Nettoyage du Registre et des Associations
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
  DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"

  ; Désassociation complète via les macros définies au début du script
  !insertmacro APP_UNASSOCIATE "alog" "Artisan.Profile"
  !insertmacro APP_UNASSOCIATE "alrm" "Artisan.Alarms"
  !insertmacro APP_UNASSOCIATE "apal" "Artisan.Palettes"
  !insertmacro APP_UNASSOCIATE "athm" "Artisan.Theme"
  !insertmacro APP_UNASSOCIATE "aset" "Artisan.Settings"
  !insertmacro APP_UNASSOCIATE "wg" "Artisan.Wheel"

  ; 6. Tentative de suppression finale du répertoire d'installation
  ; Sans /r ici pour ne pas supprimer des fichiers créés par l'utilisateur par erreur
  RMDir "$INSTDIR"

  SetAutoClose true
SectionEnd
