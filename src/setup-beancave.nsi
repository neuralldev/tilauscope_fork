; BeanCave alone, beside the operator's own Artisan (wiki/BeanCave-Standalone-Spec.md, lot 4).
; Packs dist\BeanCave (setup-beancave-win.spec). No file associations: .alog files stay Artisan's.
;   makensis /DPRODUCT_VERSION=4.3 /DPRODUCT_BUILD=47 setup-beancave.nsi

RequestExecutionLevel admin
Unicode true

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define PRODUCT_NAME "BeanCave"
!define PRODUCT_PUBLISHER "Tilau"
!define PRODUCT_WEB_SITE "https://github.com/neuralldev/tilauscope_fork"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\BeanCave.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define /ifndef PRODUCT_VERSION "0.0.0"
!define /ifndef PRODUCT_BUILD "0"
!define /date CUR_YEAR "%Y"
!searchparse /noerrors "${PRODUCT_VERSION}.0.0" "" _VER_MAJOR "." _VER_MINOR "." _VER_PATCH "." _VER_TAIL
!define PRODUCT_VERSION_NUMERIC "${_VER_MAJOR}.${_VER_MINOR}.${_VER_PATCH}"

!define MUI_ICON "beancave.ico"
!define MUI_UNICON "beancave.ico"
!define MUI_ABORTWARNING
!define MUI_LANGDLL_ALWAYSDETECT
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"

LangString DESC_AdminRequired ${LANG_ENGLISH} "Administrative privileges are required to install ${PRODUCT_NAME}.$\nPlease restart the installer as an administrator."
LangString DESC_AdminRequired ${LANG_FRENCH} "Des privilèges d'administrateur sont requis pour installer ${PRODUCT_NAME}.$\nVeuillez relancer l'installeur en tant qu'administrateur."
LangString DESC_AlreadyInstalled ${LANG_ENGLISH} "${PRODUCT_NAME} is already installed.$\n$\nClick `OK` to remove the previous version or `Cancel` to cancel this upgrade."
LangString DESC_AlreadyInstalled ${LANG_FRENCH} "${PRODUCT_NAME} est déjà installé.$\n$\nCliquez sur `OK` pour supprimer la version précédente ou sur `Annuler` pour abandonner la mise à jour."
LangString DESC_64bitOnly ${LANG_ENGLISH} "This is a 64-bit application. Your system is not 64-bit compatible."
LangString DESC_64bitOnly ${LANG_FRENCH} "Ceci est une application 64-bit. Votre système n'est pas compatible 64-bit."
LangString DESC_UninstConfirm ${LANG_ENGLISH} "Are you sure you want to remove $(^Name)? Your coffee library is kept."
LangString DESC_UninstConfirm ${LANG_FRENCH} "Êtes-vous sûr de vouloir supprimer $(^Name) ? Votre bibliothèque de cafés est conservée."

VIProductVersion "${PRODUCT_VERSION_NUMERIC}.${PRODUCT_BUILD}"
VIAddVersionKey ProductName "${PRODUCT_NAME}"
VIAddVersionKey Comments "Installer for BeanCave"
VIAddVersionKey LegalCopyright "Copyright 2025-${CUR_YEAR}, Tilau. GNU Affero General Public License"
VIAddVersionKey FileVersion "${PRODUCT_VERSION_NUMERIC}.${PRODUCT_BUILD}"
VIAddVersionKey FileDescription "${PRODUCT_NAME} Installer"
VIAddVersionKey ProductVersion "${PRODUCT_VERSION_NUMERIC}.${PRODUCT_BUILD}"

Name "${PRODUCT_NAME}"
Caption "${PRODUCT_NAME} Installer"
OutFile "beancave-win-x64-${PRODUCT_VERSION}-setup.exe"
InstallDir "$PROGRAMFILES64\BeanCave"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
ShowInstDetails show
ShowUnInstDetails show

Function .onInit
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 != "Admin"
    MessageBox MB_OK|MB_ICONSTOP "$(DESC_AdminRequired)"
    Abort
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK "$(DESC_64bitOnly)"
    Abort
  ${EndIf}
  ReadRegStr $R0 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
  StrCmp $R0 "" done
  MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(DESC_AlreadyInstalled)" /SD IDOK IDOK uninst
  Abort
  uninst:
    ClearErrors
    IfSilent 0 +3
      ExecWait '$R0 /S _?=$INSTDIR'
      Goto done
    ExecWait '$R0 _?=$INSTDIR'
  done:
FunctionEnd

Section "MainSection" SEC01
  SetShellVarContext all
  SetOutPath "$INSTDIR"
  SetOverwrite ifnewer
  File /r 'dist\BeanCave\*.*'
  CreateDirectory "$SMPROGRAMS\BeanCave"
  CreateShortCut "$SMPROGRAMS\BeanCave\BeanCave.lnk" "$INSTDIR\BeanCave.exe"
  CreateShortCut "$SMPROGRAMS\BeanCave\Uninstall.lnk" "$INSTDIR\uninst.exe"
  CreateShortCut "$DESKTOP\BeanCave.lnk" "$INSTDIR\BeanCave.exe"
SectionEnd

Section "Microsoft Visual C++ Redistributable Package (x64)" SEC02
  ExecWait '$INSTDIR\vc_redist.x64.exe /install /passive /norestart'
  Delete '$INSTDIR\vc_redist.x64.exe'
SectionEnd

Section -Post
  WriteUninstaller "$INSTDIR\uninst.exe"
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\BeanCave.exe"
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "Path" "$INSTDIR"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\BeanCave.exe"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION_NUMERIC}.${PRODUCT_BUILD}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
SectionEnd

Function un.onInit
  IfSilent +3
    MessageBox MB_ICONQUESTION|MB_YESNO|MB_TOPMOST "$(DESC_UninstConfirm)" IDYES +2
    Abort
FunctionEnd

; Only the program folder: the coffee library lives in the user's own folder and is never touched.
Section Uninstall
  SetShellVarContext all
  RMDir /r /REBOOTOK "$INSTDIR"
  Delete "$SMPROGRAMS\BeanCave\BeanCave.lnk"
  Delete "$SMPROGRAMS\BeanCave\Uninstall.lnk"
  RMDir "$SMPROGRAMS\BeanCave"
  Delete "$DESKTOP\BeanCave.lnk"
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  SetAutoClose true
SectionEnd
