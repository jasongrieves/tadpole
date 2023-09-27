import os
import logging

from sf2000ROM import sf2000ROM
static_TadpoleDir = os.path.join(os.path.expanduser('~'), '.tadpole')
static_LoggingPath = os.path.join(static_TadpoleDir, 'tadpole.log')
static_TadpoleConfigFile = os.path.join(static_TadpoleDir, 'tadpole.ini')
if __name__ == "__main__":
        # Per logger documentation, create logging as soon as possible before other hreads    
        if not os.path.exists(static_TadpoleDir):
            os.mkdir(static_TadpoleDir)
        logging.basicConfig(filename=static_LoggingPath,
                        filemode='a',
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S',
                        level=logging.DEBUG)
        logging.info("Tadpole Started")
        
# GUI imports
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import Qt, QTimer, QSize
# OS imports - these should probably be moved somewhere else
import sys
import shutil
import hashlib
import time

# Tadpole imports
import frogtool
import tadpole_functions
from tadpoleConfig import TadpoleConfig
# Dialog imports
from dialogs.SettingsDialog import SettingsDialog
from dialogs.ThumbnailDialog import ThumbnailDialog
from dialogs.BootConfirmDialog import BootConfirmDialog
from dialogs.DownloadProgressDialog import DownloadProgressDialog
from dialogs.GameShortcutIconsDialog import GameShortcutIconsDialog
from dialogs.MusicConfirmDialog import MusicConfirmDialog
from dialogs.ReadmeDialog import ReadmeDialog

#feature imports
import requests
import psutil
import json
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
import configparser
import webbrowser
import subprocess

basedir = os.path.dirname(__file__)
static_NoDrives = "N/A"
static_AllSystems = "ALL"


#Use this to poll for SD cards, turn it to False to stop polling
poll_drives = True

tpConf = TadpoleConfig()

def RunFrogTool(drive, console):
    if drive == 'N/A':
        logging.warning("You are trying to run froggy with no drive.")
        return
    print(f"Running frogtool with drive ({drive}) and console ({console})")
    logging.info(f"Running frogtool with drive ({drive}) and console ({console})")
    try:
        #TODO: should probably replace this with rebuilding the favourites list at some point
        if(console == static_AllSystems):
            #Give progress to user if rebuilding has hundreds of ROMS
            rebuildingmsgBox = DownloadProgressDialog()
            rebuildingmsgBox.progress.reset()
            rebuildingmsgBox.setText("Rebuilding roms...")
            progress = 20
            rebuildingmsgBox.showProgress(progress, True)
            rebuildingmsgBox.show()
            for console in frogtool.systems.keys():
                result = frogtool.process_sys(drive, console, False)
                #Update Progress
                progress += 10
                rebuildingmsgBox.showProgress(progress, True)
            #TODO: eventually we could return a total roms across all systems, but not sure users will care
            rebuildingmsgBox.close()
            QMessageBox.about(window, "Result", "Rebuilt all ROMS for all systems")
        else:
            result = frogtool.process_sys(drive, console, False)
            print("Result " + result)      
        #Always reload the table now that the folders are all cleaned up
        window.loadROMsToTable()
    except frogtool.StopExecution:
        pass

# SubClass QMainWindow to create a Tadpole general interface
class MainWindow (QMainWindow):
    _static_columns_GameName    = "Name"
    _static_columns_Size        = "Size"
    _static_columns_Thumbnail   = "Thumbnail"
    _static_columns_Shortcut   = "Shortcut Slot"
    _static_columns_Delete   = "Delete ROM"
    columns = [_static_columns_GameName, 
               _static_columns_Size, 
               _static_columns_Thumbnail,
               _static_columns_Shortcut,
               _static_columns_Delete]

    ROMList = []

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tadpole - SF2000 Tool")
        self.setWindowIcon(QIcon(os.path.join(basedir, 'frog.ico')))
        self.resize(1200,500)

        widget = QWidget()
        self.setCentralWidget(widget)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Load the Menus
        self.create_actions()
        self.loadMenus()

        # Create Layouts
        layout = QVBoxLayout(widget)
        selector_layout = QHBoxLayout()
        layout.addLayout(selector_layout)

        # Drive Select Widgets
        self.lbl_drive = QLabel(text="Drive:")
        self.lbl_drive.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.combobox_drive = QComboBox()
        self.combobox_drive.activated.connect(self.combobox_drive_change)
        selector_layout.addWidget(self.lbl_drive)
        selector_layout.addWidget(self.combobox_drive, stretch=3)

        #CopyButton
        self.btn_coppy_user_selected_button = QPushButton("Copy local to SD...")
        self.btn_coppy_user_selected_button.setEnabled(False)
        selector_layout.addWidget(self.btn_coppy_user_selected_button)
        self.btn_coppy_user_selected_button.clicked.connect(self.copyUserSelectedDirectoryButton)

        # Spacer
        selector_layout.addWidget(QLabel(" "), stretch=3)

        # Console Select Widgets
        self.lbl_console = QLabel(text="Console:")
        self.lbl_console.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.combobox_console = QComboBox()
        self.combobox_console.activated.connect(self.combobox_console_change)
        selector_layout.addWidget(self.lbl_console)
        selector_layout.addWidget(self.combobox_console, stretch=1)

        # Add ROMS button
        self.btn_update = QPushButton("Add ROMs...")
        selector_layout.addWidget(self.btn_update)
        self.btn_update.clicked.connect(self.copyRoms)
        
        # Add Thumbnails button
        self.btn_update_thumbnails = QPushButton("Add Thumbnails...")
        selector_layout.addWidget(self.btn_update_thumbnails )
        self.btn_update_thumbnails.clicked.connect(self.addBoxart)

        # Add Shortcut button
        self.btn_update_shortcuts_images = QPushButton("Change Game Shortcut Icons...")
        selector_layout.addWidget(self.btn_update_shortcuts_images )
        self.btn_update_shortcuts_images.clicked.connect(self.addShortcutImages)

        # Delete selected roms
        self.btn_delete_roms = QPushButton("Delete selcted ROMs...")
        self.btn_delete_roms.setEnabled(False)
        selector_layout.addWidget(self.btn_delete_roms)
        self.btn_delete_roms.clicked.connect(self.deleteROMs)

        # Game Table Widget
        self.tbl_gamelist = QTableWidget()
        self.tbl_gamelist.setColumnCount(len(self.columns))
        self.tbl_gamelist.setHorizontalHeaderLabels(self.columns)
        self.tbl_gamelist.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tbl_gamelist.horizontalHeader().resizeSection(0, 300) 
        self.tbl_gamelist.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_gamelist.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_gamelist.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_gamelist.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_gamelist.cellClicked.connect(self.catchTableCellClicked)
        self.tbl_gamelist.cellChanged.connect(self.catchTableCellChanged)
        self.tbl_gamelist.horizontalHeader().sectionClicked.connect(self.headerClicked)

        layout.addWidget(self.tbl_gamelist)
        

        # Reload Drives Timer
        # This is run once per second to check if any new SD cards have been inserted.
        # Ideally we would hook this into a trigger rather than polling for changes.
        # The resource cost of polling seems to be quite low though
        self.timer = QTimer()
        self.timer.timeout.connect(self.reloadDriveList)
        self.timer.start(1000)


    def toggle_features(self, enable: bool):
        """Toggles program features on or off"""
        features = [window.btn_update_thumbnails,
                    window.btn_update,
                    window.btn_update_shortcuts_images,
                    window.combobox_console,
                    window.combobox_drive,
                    window.menu_os,
                    window.menu_roms,
                    window.tbl_gamelist]
        for feature in features:
            feature.setEnabled(enable)
    
    def create_actions(self):
        # File Menu
        self.about_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation),
                                    "&About",
                                    self,
                                    triggered=self.about)
        self.exit_action = QAction("E&xit", self, shortcut="Ctrl+Q",triggered=self.close)

    def loadMenus(self):
        self.menu_file = self.menuBar().addMenu("&File")
        Settings_action = QAction("Settings...", self, triggered=self.Settings)
        self.menu_file.addAction(Settings_action)
        self.menu_file.addAction(self.exit_action)

        # OS Menu
        self.menu_os = self.menuBar().addMenu("&OS")
        #Sub-menu for updating Firmware
        self.menu_os.menu_update = self.menu_os.addMenu("Firmware")
        action_detectOSVersion = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Detect and update firmware", self, triggered=self.detectOSVersion)
        self.menu_os.menu_update.addAction(action_detectOSVersion)
        action_updateTo20230803  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Manually change to 2023.08.03 (V1.6)", self, triggered=self.Updateto20230803)                                                                              
        self.menu_os.menu_update.addAction(action_updateTo20230803)   
        self.action_updateToV1_5  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Manually change to 2023.04.20 (V1.5)  - Not recommended", self, triggered=self.UpdatetoV1_5)                                                                              
        self.menu_os.menu_update.addAction(self.action_updateToV1_5)
        self.menu_os.menu_update.addSeparator()
        action_battery_fix  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Battery Fix - Built by commnity (Improves battery life & shows low power warning)", self, triggered=self.Battery_fix)                                                                              
        self.menu_os.menu_update.addAction(action_battery_fix)
        action_bootloader_patch  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Bootloader Fix - Built by commnity (Prevents device from not booting and corrupting SD card when changing files on SD card)", self, triggered=self.bootloaderPatch)                                                                              
        self.menu_os.menu_update.addAction(action_bootloader_patch)   
        #Sub-menu for updating themes
        self.menu_os.menu_change_theme = self.menu_os.addMenu("Theme")
        try:
            self.theme_options = tadpole_functions.get_themes()
        except (ConnectionError, requests.exceptions.ConnectionError):
            self.status_bar.showMessage("Error loading external theme resources.  Reconnect to internet and try restarting tadpole.", 20000)
            error_action = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)),
                                   "Error Loading External Resources!",
                                   self)
            error_action.setDisabled(True)
            self.menu_os.menu_change_theme.addAction(error_action)
        else:
            for theme in self.theme_options:
                self.menu_os.menu_change_theme.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)),
                                                theme,
                                                self,
                                                triggered=self.change_theme))
        self.menu_os.menu_change_theme.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)),
                                        "Check out theme previews and download more themes...",
                                        self,
                                        triggered=lambda: webbrowser.open(("https://zerter555.github.io/sf2000-collection/"))))
        self.menu_os.menu_change_theme.addSeparator()
        self.menu_os.menu_change_theme.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)),
                                        "Update From Local File...",
                                        self,
                                        triggered=self.change_theme)) 
        # Sub-menu for changing background music
        self.menu_os.menu_change_music = self.menu_os.addMenu("Background Music")
        try:
            self.music_options = tadpole_functions.get_background_music()
        except (ConnectionError, requests.exceptions.ConnectionError):
            self.status_bar.showMessage("Error loading external music resources. Reconnect to internet and try restarting tadpole.", 20000)
            error_action = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)),
                                   "Error Loading External Resources!",
                                   self)
            error_action.setDisabled(True)
            self.menu_os.menu_change_music.addAction(error_action)
        else:
            for music in self.music_options:
                self.menu_os.menu_change_music.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)),
                                                music,
                                                self,
                                                triggered=self.change_background_music))
        self.menu_os.menu_change_music.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)),
                                        "Check out more background music to download...",
                                        self,
                                        triggered=lambda: webbrowser.open(("https://zerter555.github.io/sf2000-collection/"))))
        self.menu_os.menu_change_music.addSeparator()
        self.menu_os.menu_change_music.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)),
                                        "Upload from Local File...",
                                        self,
                                        triggered=self.change_background_music))

        #Menus for boot logo
        self.menu_os.menu_boot_logo = self.menu_os.addMenu("Boot Logo")
        try:
            self.boot_logos  = tadpole_functions.get_boot_logos()
        except (ConnectionError, requests.exceptions.ConnectionError):
            self.status_bar.showMessage("Error loading external theme resources.  Reconnect to internet and try restarting tadpole.", 20000)
            error_action = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)),
                                   "Error Loading External Resources!",
                                   self)
            error_action.setDisabled(True)
            self.menu_os.menu_boot_logo.addAction(error_action)
        else:
            for bootlogo in self.boot_logos:
                self.menu_os.menu_boot_logo.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)),
                                                bootlogo,
                                                self,
                                                triggered=self.download_bootlogo))
        self.menu_os.menu_boot_logo.addAction(QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)),
                                            "Check out and download boot logos...",
                                            self,
                                            triggered=lambda: webbrowser.open(("https://zerter555.github.io/sf2000-collection/"))))
        UpdateBootLogoAction  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)), 
                                        "Upload from Local File...", 
                                        self, 
                                        triggered=self.changeBootLogo)
        self.menu_os.menu_boot_logo.addAction(UpdateBootLogoAction)

        #Menus for console logos
        self.menu_os.menu_bios = self.menu_os.addMenu("Emulator BIOS")
        self.GBABIOSFix_action = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Update GBA BIOS", self, triggered=self.GBABIOSFix)
        self.menu_os.menu_bios.addAction(self.GBABIOSFix_action)

        # Consoles Menu
        self.menu_roms = self.menuBar().addMenu("Consoles")
        RebuildAll_action = QAction("Refresh all thumbnails and ROMs", self, triggered=self.rebuildAll)
        self.menu_roms.addAction(RebuildAll_action)
        BackupAllSaves_action = QAction("Backup All Consoles ROMs saves...", self, triggered=self.createSaveBackup)
        self.menu_roms.addAction(BackupAllSaves_action)     
        # Help Menu
        self.menu_help = self.menuBar().addMenu("&Help")
        action_sf2000_boot_light  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Fix SF2000 not booting - Attemps to fix only the firmaware file (bisrv.asd) ", self, triggered=self.FixSF2000BootLight)                                                                              
        self.menu_help.addAction(action_sf2000_boot_light)
        action_sf2000_boot  = QAction(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)), "Fix SF2000 not booting - Reformats SD card and reinstalls all OS files", self, triggered=self.FixSF2000Boot)                                                                              
        self.menu_help.addAction(action_sf2000_boot)
        self.menu_help.addSeparator()
        self.readme_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarContextHelpButton),
                                     "Read Me",
                                     triggered=self.show_readme)
        self.menu_help.addAction(self.readme_action)
        self.menu_help.addSeparator()
        self.menu_help.addAction(self.about_action)


    def catchTableCellChanged(self,changedRow,changedColumn):
        print(f"Changed Cell for ({changedRow},{changedColumn})")
        if self.columns[changedColumn] == self._static_columns_GameName:
            # Update the game name
            self.ROMList[changedRow].setTitle(self.sender().itemAt(changedColumn,changedRow).text())

    def catchTableCellClicked(self, clickedRow, clickedColumn):
        print(f"clicked Cell for ({clickedRow},{clickedColumn})")
        objGame = self.ROMList[clickedRow]
        if self.tbl_gamelist.horizontalHeaderItem(clickedColumn).text() == self._static_columns_Thumbnail:  
            self.viewThumbnail(objGame.ROMlocation)
        elif self.tbl_gamelist.horizontalHeaderItem(clickedColumn).text() == self._static_columns_Delete: 
            self.deleteROM(objGame.ROMlocation)
        #Only enable deleting when selcted
        if clickedColumn == 0:
            selected = self.tbl_gamelist.selectedItems()
            if selected:
                self.btn_delete_roms.setEnabled(True)
            else:
                self.btn_delete_roms.setEnabled(False)
        else:
            self.btn_delete_roms.setEnabled(False)


    def headerClicked(self, column):
        #Only enable deleting when selcted
        if column == 0:
            selected = window.tbl_gamelist.selectedItems()
            if selected:
                self.btn_delete_roms.setEnabled(True)
            else:
                self.btn_delete_roms.setEnabled(False)
        else:
            self.btn_delete_roms.setEnabled(False)
        
    def processGameShortcuts(self):
        drive = self.combobox_drive.currentText()
        console = self.combobox_console.currentText()
        for i in range(self.tbl_gamelist.rowCount()):
            comboBox = self.tbl_gamelist.cellWidget(i, 3)
            #if its blank, it doesn't have a position so move on
            if comboBox.currentText() == '':
                continue
            else:
                position = int(comboBox.currentText())
                #position is 0 based
                position = position - 1
                game = self.tbl_gamelist.item(i, 0).text()
                tadpole_functions.changeGameShortcut(drive, console, position, game)
    



    """
    Reloads the drive list to check whether there have been any changes
    i.e current drive unplugged, new drives added, etc
    """
    def reloadDriveList(self):
        #If polling is disabled don't do anything
        if poll_drives == True:
            current_drive = self.combobox_drive.currentText()
            self.combobox_drive.clear()
            localdrive = tpConf.getLocalUserDirectory()
            #Check whether a local drive is configured.
            if localdrive != tpConf._static_general_userDirectory_DEFAULT:
                self.combobox_drive.addItem(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)),
                                                localdrive,
                                                localdrive)
            #Load in all mounted partitions that look Froggy
            for drive in psutil.disk_partitions():
                if(tadpole_functions.checkDriveLooksFroggy(drive.mountpoint)):
                    self.combobox_drive.addItem(QIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)),
                                                drive.mountpoint,
                                                drive.mountpoint)

            # Check if at least one frog drive is also configured. local + frog will mean at least 2 drives.
            if localdrive != tpConf._static_general_userDirectory_DEFAULT and len(self.combobox_drive) > 1:
                self.btn_coppy_user_selected_button.setEnabled(True)
            else:
                self.btn_coppy_user_selected_button.setEnabled(False)

            if len(self.combobox_drive) > 0:
                self.toggle_features(True)
                
                #TODO: Replace this a comparison of the list items instead.
                if(current_drive == static_NoDrives):
                    print("New drive detected")
                    self.status_bar.showMessage("New SF2000 Drive(s) Detected.", 2000)
                    logging.info(f"Automatically triggering drive change because a new drive connected")
                    self.combobox_drive_change()
                    
            else:
                # disable functions if nothing is in the combobox
                self.combobox_drive.addItem(QIcon(), static_NoDrives, static_NoDrives)
                self.status_bar.showMessage("No SF2000 Drive Detected. Please insert SD card and try again.", 2000)
                self.toggle_features(False)
                #TODO Should probably also clear the table of the ROMs that are still listed
            self.combobox_drive.setCurrentText(current_drive)

    def testFunction(self):
        print("Called test function. Remember to disable this before publishing")
    
    def Settings(self):
        SettingsDialog(tpConf).exec()
        if(self.combobox_drive.currentText() != static_NoDrives):
            RunFrogTool(self.combobox_drive.currentText(), self.combobox_console.currentText())

    def detectOSVersion(self):
        print("Tadpole~DetectOSVersion: Trying to read bisrv hash")
        drive = self.combobox_drive.currentText()
        msg_box = DownloadProgressDialog()
        msg_box.setText("Detecting firmware version")
        msg_box.show()
        try:
            msg_box.showProgress(50, True)
            detectedVersion = tadpole_functions.bisrv_getFirmwareVersion(os.path.join(drive,"bios","bisrv.asd"))
            if not detectedVersion:
                detectedVersion = "Version Not Found"
            #TODO: move this from string base to something else...or at lesat make sure this gets updated when/if new firmware gets out there
            if detectedVersion == "2023.04.20 (V1.5)":
                msg_box.close()
                qm = QMessageBox
                ret = qm.question(self,"Detected OS Version", f"Detected version: "+ detectedVersion + "\nDo you want to update to the latest firmware?" , qm.Yes | qm.No)
                if ret == qm.Yes:
                    self.Updateto20230803()
                else:
                    return False
            elif detectedVersion == "2023.08.03 (V1.6)":
                msg_box.close()
                QMessageBox.about(self, "Detected OS Version", f"You are already on the latest firmware: {detectedVersion}")
                return True
            else:
                msg_box.close()
                QMessageBox.about(self, "Detected OS Version", f"Cannot update from: {detectedVersion}")
                return True

        except Exception as e:
            msg_box.close()
            logging.error("tadpole~detectOSVersion: Error occured while trying to find OS Version" + str(e))
            return
    
    def addBoxart(self):
        drive = self.combobox_drive.currentText()
        system = self.combobox_console.currentText()
        rom_path = os.path.join(drive,system)
        romList = frogtool.getROMList(rom_path)
        msgBox = DownloadProgressDialog()
        failedConversions = 0
        #Check what the user has configured; upload or download
        ovewrite = tpConf.getThumbnailOverwrite()
        if not tpConf.getThumbnailDownload():
            directory = QFileDialog.getExistingDirectory()
            if directory == '':
                    return
            files = os.listdir(directory)
            #Setup progress as these can take a while
            msgBox.progress.setMaximum(len(romList))
            msgBox.setText("Copying thumbnails for zips")
            msgBox.showProgress(0, True)
            msgBox.show()
            for i, newThumbnail in enumerate(files):
                newThumbnailName = os.path.splitext(newThumbnail)[0]
                newThumbnailPath = os.path.join(directory, newThumbnail)
                #Only copy images over from that folder
                if newThumbnail.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    for rom in romList:
                        romName = os.path.splitext(rom)[0]
                        if newThumbnailName == romName:
                            rom_full_path = os.path.join(rom_path, rom)
                            if not tadpole_functions.addThumbnail(rom_full_path, drive, system, newThumbnailPath, ovewrite):
                                failedConversions += 1
                msgBox.showProgress(i, True)
        #User wants to download romart from internet
        else:
            QMessageBox.about(self, "Add Thumbnails", "You have Tadpole configured to download thumbnails automatically. \
For this to work, your roms must be in ZIP files and the name of that zip must match their common released English US localized \
name.  Please refer to https://github.com/EricGoldsteinNz/libretro-thumbnails/tree/master if Tadpole isn't finding \
the thumbnail for you. ")
            #ARCADE can't get ROM art, so just return
            if system == "ARCADE":
                QMessageBox.about(self, "Add Thumbnails", "Custom Arcade ROMs cannot have thumbnails at this time.")
                return
            #Need the url for scraping the png's, which is different
            ROMART_baseURL_parsing = "https://github.com/EricGoldsteinNz/libretro-thumbnails/tree/master/"
            ROMART_baseURL = "https://raw.githubusercontent.com/EricGoldsteinNz/libretro-thumbnails/master/"
            art_Type = "/Named_Snaps/"
            ROMArt_console = {  
                "FC":     "Nintendo - Nintendo Entertainment System",
                "SFC":    "Nintendo - Super Nintendo Entertainment System",
                "MD":     "Sega - Mega Drive - Genesis",
                "GB":     "Nintendo - Game Boy",
                "GBC":    "Nintendo - Game Boy Color",
                "GBA":    "Nintendo - Game Boy Advance", 
                "ARCADE": ""
            }
            msgBox.setText("Downloading thumbnails...")
            msgBox.show()

            zip_files = os.scandir(os.path.join(drive,system))
            zip_files = list(filter(frogtool.check_zip, zip_files))
            msgBox.setText("Trying to find thumbnails for " + str(len(zip_files)) + " ROMs\n" + ROMArt_console[system])
            msgBox.progress.reset()
            msgBox.progress.setMaximum(len(zip_files)+1)
            msgBox.progress.setValue(0)
            QApplication.processEvents()
            #Scrape the url for .png files
            url_for_scraping = ROMART_baseURL_parsing + ROMArt_console[system] + art_Type
            response = requests.get(url_for_scraping)
            # BeautifulSoup magically find ours PNG's and ties them up into a nice bow
            soup = BeautifulSoup(response.content, 'html.parser')
            json_response = json.loads(soup.contents[0])
            png_files = []
            for value in json_response['payload']['tree']['items']:
                png_files.append(value['name'])
            for i, newThumbnail in enumerate(png_files):
                newThumbnailName = os.path.splitext(newThumbnail)[0]
                #Only copy images over from the list
                if newThumbnail.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    for rom in romList:
                        newThumbnailPath = os.path.join(rom_path, newThumbnail)
                        romName = os.path.splitext(rom)[0]
                        if newThumbnailName == romName:
                            #download the png
                            rom_png_url = ROMART_baseURL + ROMArt_console[system] + art_Type + newThumbnail
                            rom_full_path = os.path.join(rom_path, rom)
                            #If it finds it, download it and add it
                            if tadpole_functions.downloadFileFromGithub(newThumbnailPath, rom_png_url):
                                if not tadpole_functions.addThumbnail(rom_full_path, drive, system, newThumbnailPath, ovewrite): 
                                    failedConversions += 1
                msgBox.showProgress(i, True)
        msgBox.close()
        if failedConversions == 0:
            QMessageBox.about(self, "Add thubmnails", "ROM thumbnails successfully changed")
            RunFrogTool(drive, system)
            return True
        else:
            QMessageBox.about(self, "Add thubmnails", "Adding thumbnails completed, but " + str(failedConversions) + " failed to convert.")
            RunFrogTool(drive, system)
            return False
        
    def change_background_music(self):
        """event to change background music"""
        if self.sender().text() == "Upload from Local File...":  # handle local file option
            d = MusicConfirmDialog()
            local = True
        else:  # handle preset options
            d = MusicConfirmDialog(self.sender().text(), self.music_options[self.sender().text()])
            local = False
        if d.exec():
            if local:
                self.BGM_change(d.music_file)
            else:
                self.BGM_change(self.music_options[self.sender().text()])
        if os.path.exists(os.path.join(static_TadpoleDir, 'preview.wav' )):
            os.remove(os.path.join(static_TadpoleDir, 'preview.wav'))
    def about(self):
        QMessageBox.about(self, "About Tadpole", 
                                "Tadpole was created by EricGoldstein based on the original work \
from tzlion on frogtool. Special thanks also goes to wikkiewikkie & Jason Grieves for many amazing improvements")

    def GBABIOSFix(self):
        drive = self.combobox_drive.currentText()
        try:
            tadpole_functions.GBABIOSFix(drive)
        except tadpole_functions.Exception_InvalidPath:
            QMessageBox.about(self, "GBA BIOS Fix", "An error occurred. Please ensure that you have the right drive \
            selected and <i>gba_bios.bin</i> exists in the <i>bios</i> folder")
            return
        QMessageBox.about(self, "GBA BIOS Fix", "BIOS successfully copied")
        
    def changeBootLogo(self):
        msgBox = DownloadProgressDialog()
        msgBox.setText(" Loading current boot logo...")
        msgBox.show()
        msgBox.showProgress(50, True)
        dialog = BootConfirmDialog(self.combobox_drive.currentText(), basedir)
        msgBox.close()
        change = dialog.exec()
        if change:
            newLogoFileName = dialog.new_viewer.path
            print(f"user tried to load image: {newLogoFileName}")
            if newLogoFileName is None or newLogoFileName == "":
                print("user cancelled image select")
                return
            try:
                msgBox = DownloadProgressDialog()
                msgBox.setText("Updating boot logo...")
                msgBox.show()
                msgBox.showProgress(10, True)
                success = tadpole_functions.changeBootLogo(os.path.join(self.combobox_drive.currentText(),
                                                              "bios",
                                                              "bisrv.asd"),
                                                 newLogoFileName, msgBox)
                msgBox.close()
            except tadpole_functions.Exception_InvalidPath:
                QMessageBox.about(self, "Change Boot Logo", "An error occurred. Please ensure that you have the right \
                drive selected and <i>bisrv.asd</i> exists in the <i>bios</i> folder")
                return
            if success:
                QMessageBox.about(self, "Change Boot Logo", "Boot logo successfully changed")
            else:
                QMessageBox.about(self, "Change Boot Logo", "Could not update boot logo.  Have you changed the firmware with another tool?  Tadpole only supports stock firmware files")

    def UnderDevelopmentPopup(self):
        QMessageBox.about(self, "Development", "This feature is still under development")
        
    def combobox_drive_change(self):
        newDrive = self.combobox_drive.currentText()
        console = self.combobox_console.currentText()
        logging.info(f"combobox for drive changed to ({newDrive})")
        if (newDrive != static_NoDrives):
            RunFrogTool(newDrive,console)

    def combobox_console_change(self):
        console = self.combobox_console.currentText()
        logging.info(f"Dialog for console changed to ({console})")
        # ERIC: We shouldnt run frogtool as soon as the drive is opened. This is a lot of unnecessary processing.  
        # Jason: agree it takes processing, but there were some crashing bugs where we got out of sync with the table
        # Jason: and if the user changes anything outside of Tadpole it helps keep in sync.  Pros and cons
        RunFrogTool(self.combobox_drive.currentText(),console)

    def show_readme(self):
        self.readme_dialog = ReadmeDialog(basedir)
        self.readme_dialog.show()

    def UpdatetoV1_5(self):
        url = "https://api.github.com/repos/EricGoldsteinNz/SF2000_Resources/contents/OS/V1.5"
        self.UpdateDevice(url)
    
    def Updateto20230803(self):
        url = "https://api.github.com/repos/EricGoldsteinNz/SF2000_Resources/contents/OS/20230803"
        self.UpdateDevice(url)

    def Battery_fix(self):
        qm = QMessageBox()
        ret = qm.question(self,'Patch Firmware?', "Are you sure you want to patch the firmware? The system will also check if the latest firmware is on the SD card, so make sure you are up to date." , qm.Yes | qm.No)
        if ret == qm.No:
            return
        battery_patcher = tadpole_functions.BatteryPatcher(os.path.join(self.combobox_drive.currentText(),"bios","bisrv.asd"))
        if battery_patcher.check_patch_applied():
            QMessageBox.about(self, "Status","You already have the battery patch applied")
            return
        #Order matters, if they are on patch, they will fail so do this second
        elif not battery_patcher.check_latest_firmware():
            qm = QMessageBox()
            ret = qm.question(self,'Status', "This version of tadpole only supports battery patching of v1.6 firmware.  Do you want to downlaod it now?" , qm.Yes | qm.No)
            if ret == qm.No:
                return
            else:
                self.Updateto20230803()
        #get some progress for the user
        UpdateMsgBox = DownloadProgressDialog()
        UpdateMsgBox.setText("Patching firmware...")
        UpdateMsgBox.showProgress(1, True)
        UpdateMsgBox.show()
        if battery_patcher.patch_firmware(UpdateMsgBox.progress):
            QMessageBox.about(self, "Status","Firmware patched with the battery improvements")
        else:
            QMessageBox.about(self, "Failure","Firmware was not patched with the battery improvements.  Are you already up to date?")
        UpdateMsgBox.close()

    def viewThumbnail(self, rom_path):
        self.window_thumbnail = ThumbnailDialog(rom_path)  
        result = self.window_thumbnail.exec()
        drive = self.combobox_drive.currentText()
        system = self.combobox_console.currentText()
        if result:
            newLogoFileName = self.window_thumbnail.new_viewer.path
            print(f"user tried to load image: {newLogoFileName}")
            if newLogoFileName is None or newLogoFileName == "":
                print("user cancelled image select")
                return
            if tadpole_functions.addThumbnail(rom_path, drive, system, newLogoFileName, True):
                QMessageBox.about(self, "Change ROM Logo", "ROM thumbnails successfully changed")
                RunFrogTool(drive,system)
                return True
            else:
                QMessageBox.about(self, "Change ROM Cover", "Unable to convert thumbnail for ROM")
                RunFrogTool(drive,system)
                return False

    def formatAndDownloadOSFiles(self):
            foundSD = False
            QMessageBox.about(self, "Formatting", "First format your SD card. After pressing OK the partition tool will come up enabling you to format it.\n\n\
    Format it to with a drive letter and to FAT32.  It may say the drive is in use; that is Normal as Tadpole is looking for it.")
            try:
                subprocess.Popen('diskmgmt.msc', shell=True)
            except:
                logging.error("Can't run diskpart.  Wrong OS?")
            qm = QMessageBox()
            ret = qm.question(self, "Formatting", "Did you finish formatting it to FAT32?  Tadpole will now try to detect it.")
            if ret == qm.No:
                QMessageBox.about(self, "Formatting", "Please try formating the SD card and trying again.")
                return False
            for drive in psutil.disk_partitions():
                if not os.path.exists(drive.mountpoint):
                    logging.info("Formatting prevented {drive} can't be read")
                    continue
                dir = os.listdir(drive.mountpoint)
                #Windows puts in a System inFormation item that is hidden
                if len(dir) > 1:
                    logging.info("Formatting prevented {drive} isn't empty")
                    continue
                if(drive.mountpoint == f'C:\\'):
                    logging.info("Formatting prevented, be ultra safe don't let them format C")
                    continue
                ret = qm.question(self, "Empty SD card found", "Is the right SD card: " + drive.mountpoint + "?")
                if ret == qm.Yes:
                    correct_drive = drive.mountpoint
                    foundSD = True
                    logging.info("SD card was formatted and is empty")
                    break
                if ret == qm.No:
                    continue
            if foundSD == False:
                QMessageBox.about(self, "Empty SD card not found", "Looks like none of the mounted drives in Windows are empty SD cards. Are you sure you formatted it and it is empty?")
                return False
            msgBox = DownloadProgressDialog()
            msgBox.setText("Downloading Firmware Update.")
            msgBox.show()
            tadpole_functions.DownloadOSFiles(correct_drive, msgBox.progress)
            ret = QMessageBox.question(self, "Try booting",  "Try putting the SD card in the SF2000 and starting it.  Did it work?")
            if ret == qm.No:
                QMessageBox.about(self, "Not booting", "Sorry it didn't work; Consult https://github.com/vonmillhausen/sf2000#bootloader-bug or ask for help on Discord https://discord.gg/retrohandhelds.")
                return False
            
            ret = QMessageBox.question(self, "Success",  "Congrats!  Now put the SD card back into the computer.\n\n\
    If you got into a bad state without patching the bootloader, you should patch it so you can make changes safely.  Do you want to patch the bootloader?")
            if ret == qm.No:
                return True
            self.bootloaderPatch()
            return True

    def deleteROM(self, rom_path):
        console = self.combobox_console.currentText()
        drive = self.combobox_drive.currentData()
        qm = QMessageBox
        ret = qm.question(self,'Delete ROM?', "Are you sure you want to delete " + rom_path +" and rebuild the ROM list? " , qm.Yes | qm.No)
        if ret == qm.Yes:
            try:
                if console == 'ARCADE':
                    arcadeZIPROM = tadpole_functions.extractFileNameFromZFB(rom_path)
                    arcadeZIPPath = os.path.join(drive, console, 'bin', arcadeZIPROM)
                    os.remove(arcadeZIPPath)
                os.remove(rom_path)
            except Exception:
                QMessageBox.about(self, "Error","Could not delete file.")
            RunFrogTool(drive,console)
        return

    def addToShortcuts(self, rom_path):
        qm = QMessageBox
        qm.setText("Time to set the rompath!")

    def BGM_change(self, source=""):
        # Check the selected drive looks like a Frog card
        drive = self.combobox_drive.currentText()
        
        if not tadpole_functions.checkDriveLooksFroggy(drive):
            QMessageBox.about(self, "Something doesn't Look Right", "The selected drive doesn't contain critical \
            SF2000 files. The action you selected has been aborted for your safety.")
            return

        msg_box = DownloadProgressDialog()
        msg_box.setText("Downloading background music.")
        msg_box.show()
        msg_box.showProgress(25, True)

        if source[0:4] == "http":  # internet-based
            result = tadpole_functions.changeBackgroundMusic(drive, url=source)
        else:  # local resource
            result = tadpole_functions.changeBackgroundMusic(drive, file=source)

        if result:
            msg_box.close()
            QMessageBox.about(self, "Success", "Background music changed successfully")
        else:
            msg_box.close()
            QMessageBox.about(self, "Failure", "Something went wrong while trying to change the background music")

    def bootloaderPatch(self):
        qm = QMessageBox
        ret = qm.question(self, "Download fix", "Patching the bootloader will require your SD card and that the SF2000 is well charged.  Do you want to download the fix?")
        if ret == qm.No:
            return
        #cleanup previous files
        drive = self.combobox_drive.currentText()
        if drive == "N/A":
            ret = QMessageBox().question(self, "Insert SD Card", "To fix the bootloader, you must have your SD card plugged in as it downloads critical \
    updates to the SD card to update the bootlaoder.  Do you want to plug it in and try detection agian?")
            if ret == qm.Yes:
                self.bootloaderPatch()
            elif ret == qm.No:
                QMessageBox().about("Update skipped", "No problem.  Just remember if you change any files on the SD card without the bootlaoder \
    The SF2000 may not boot.  You can always try this fix again in the Firmware options")
                logging.info("User skipped bootloader")
                return
        bootloaderPatchDir = os.path.join(drive,"/UpdateFirmware/")
        bootloaderPatchPathFile = os.path.join(drive,"/UpdateFirmware/Firmware.upk")
        bootloaderChecksum = "eb7a4e9c8aba9f133696d4ea31c1efa50abd85edc1321ce8917becdc98a66927"
        #Let's delete old stuff if it exits incase they tried this before and failed
        if Path(bootloaderPatchDir).is_dir():
            shutil.rmtree(bootloaderPatchDir)
        os.mkdir(bootloaderPatchDir)
        #Download file, and continue if its successful
        if tadpole_functions.downloadFileFromGithub(bootloaderPatchPathFile, "https://github.com/EricGoldsteinNz/SF2000_Resources/blob/60659cc783263614c20a60f6e2dd689d319c04f6/OS/Firmware.upk?raw=true"):
            #check file correctly download
            with open(bootloaderPatchPathFile, 'rb', buffering=0) as f:
                downloadedchecksum = hashlib.file_digest(f, 'sha256').hexdigest()
            #check if the hash matches
            print("Checking if " + bootloaderChecksum + " matches " + downloadedchecksum)
            if bootloaderChecksum != downloadedchecksum: # TODO Consider that this may create an infinite loop if the file becomes unavailable or changes
                QMessageBox().about(self, "Update not successful", "The downloaded file did not download correctly.\n\
    Tadpole will try the process again. For more help consult https://github.com/vonmillhausen/sf2000#bootloader-bug\n\
    or ask for help on Discord https://discord.gg/retrohandhelds.")
                self.bootloaderPatch()
            ret = QMessageBox().warning(self, "Bootloader Fix", "Downloaded bootloader to SD card.\n\n\
    You can keep this window open while you appy the fix:\n\
    1. Eject the SD card from your computer\n\
    2. Put the SD back in the SF2000)\n\
    3. Turn the SF2000 on\n\
    4. You should see a message in the lower-left corner of the screen indicating that patching is taking place.\n\
    5. The process will only last a few seconds\n\
    6. You should see the main menu on the SF2000\n\
    7. Power off the SF2000\n\
    8. Remove the SD card \n\
    9. Connect the SD card back to your computer \n\n\
    Did the update complete successfully?", qm.Yes | qm.No)
            if Path(bootloaderPatchDir).is_dir():
                shutil.rmtree(bootloaderPatchDir)
            if ret == qm.Yes:
                QMessageBox().about(self, "Update complete", "Your SF2000 should now be safe to use with \
    Tadpole. Major thanks to osaka#9664 on RetroHandhelds Discords for this fix!\n\n\
    Remember, you only need to apply the bootloader fix once to your SF2000.  Unlike other changes affecting the SD card, this changes the code running on the SF2000.")
                logging.info("Bootloader installed correctly...or so the user says")
                return
            else:
                QMessageBox().about(self, "Update not successful", "Based on your answer, the update did not complete successfully.\n\n\
    Consult https://github.com/vonmillhausen/sf2000#bootloader-bug or ask for help on Discord https://discord.gg/retrohandhelds. ")
                logging.error("Bootloader failed to install...or so the user says")
                return
        else:
            QMessageBox().about(self, "Download did not complete", "Please ensure you have internet and retry the fix")
            logging.error("Bootloader failed to download")
            return


    def FixSF2000BootLight(self):
        drive = self.combobox_drive.currentText()
        temp_file_bios_path = os.path.join(drive, 'bios', 'file.tmp')
        qm = QMessageBox
        ret = qm.question(self, "SF2000 not booting", "If your SF2000 won't boot, you likely hit the bootloader bug or have broken some critical files.  This process attempts to restore your SF2000.\n\n\
This only works on the Windows OS.\n\nDo you want to continue?")
        if ret == qm.No:
            return
        #create a new file in bios
        Path.touch(temp_file_bios_path)
        #delete that file
        os.remove(temp_file_bios_path)
        ret = qm.question(self, "Ready to test", "Please take out the SD card and plug it into the SF2000 and turn it on.\n\n\
Did it boot?")
        if ret == qm.Yes:
            QMessageBox.about(self, "Success", "Please apply the bootloader fix now to avoid this issue again.  Sending you there now")
            self.bootloaderPatch()
            return
        if ret == qm.No: 
            #If no, repeat
            #create a new file in bios
            Path.touch(temp_file_bios_path)
            #delete that file
            os.remove(temp_file_bios_path)
            ret = qm.question(self, "Try again", "We attempted one more fix at replacing the bisrv.asd file.  Please take out the SD card now and try one more time\n\n\
Did it boot this time?")
            if ret == qm.Yes:
                QMessageBox.about(self, "Success", "Please apply the bootloader fix now to avoid this issue again.  Sending you there now")
                self.bootloaderPatch()
                return
            if ret == qm.No: 
                QMessageBox.about(self, "Error", "The simple fix did not succeed.  You need to reformat and install OS files.\n\n\
Sending you to that option now")
                self.FixSF2000Boot()
                return
    def FixSF2000Boot(self):
        qm = QMessageBox
        ret = qm.question(self, "SF2000 not booting", "If your SF2000 won't boot, you likely hit the bootloader bug or have broken some critical files.  This process attempts to restore your SF2000.\n\n\
This process will delete ALL SAVES AND ROMS, so if you want to save those, cancel out and do so.\n\n\
This process is only tested on Windows and will not work on Linux/Mac.\n\nDo you want to proceed?")
        if ret == qm.No:
            return 
        #Turn off polling since we are going to mess with the SD card
        self.turn_off_polling()
        #Stop access to the drives
        self.combobox_drive.addItem(QIcon(), static_NoDrives, static_NoDrives)
        self.status_bar.showMessage("No SF2000 Drive Detected. Please insert SD card and try again.", 20000)
        self.toggle_features(False)
        self.formatAndDownloadOSFiles()
        self.turn_on_polling()

    def turn_off_polling(self):
        global poll_drives 
        poll_drives = False

    def turn_on_polling(self):
        global poll_drives 
        poll_drives = True

    def UpdateDevice(self, url):
        drive = self.combobox_drive.currentText()
        msgBox = DownloadProgressDialog()
        msgBox.setText("Downloading Firmware Update.")
        msgBox.show()
        msgBox.showProgress(0, True)
        if tadpole_functions.downloadDirectoryFromGithub(drive, url, msgBox.progress):
            msgBox.close()
            QMessageBox.about(self, "Success","Update successfully downloaded")
        else:
            msgBox.close()
            QMessageBox.about(self, "Failure","ERROR: Something went wrong while trying to download the update")

    def change_theme(self, url):
        qm = QMessageBox()
        ret = qm.question(self,'Heads up', "Changing themes will ovewrite your game shortcut icons.  You can change them again after the theme is applied.  Are you sure you want to change your theme?" , qm.Yes | qm.No)
        if ret == qm.No:
            return
        drive = self.combobox_drive.currentText()
        #TODO error handling
        if not self.sender().text() == "Update From Local File...":
            url =  self.theme_options[self.sender().text()]
        msgBox = DownloadProgressDialog()
        msgBox.setText("Updating Theme...")
        msgBox.show()
        progress = 1
        msgBox.showProgress(progress, True)
        """event to change theme"""
        if self.sender().text() == "Update From Local File...":  # handle local file option
            theme_zip = filename, _ = QFileDialog.getOpenFileName(self,"Select Theme ZIP File",'',"Theme ZIP file (*.zip)")
            if filename:
                result = tadpole_functions.changeTheme(drive, "", theme_zip[0], msgBox.progress)
                msgBox.close()
                if result:
                    QMessageBox.about(self, "Success", "Theme changed successfully")
                else:
                    QMessageBox.about(self, "Failure", "Something went wrong while trying to change the theme")

        elif url[0:4] == "http":  # internet-based
                result = tadpole_functions.changeTheme(drive,url, "", msgBox.progress)
                msgBox.close()
                QMessageBox.about(self, "Success", "Theme changed successfully")
        else:
            QMessageBox.about(self, "Failure", "Something went wrong while trying to change the theme")

    def download_bootlogo(self):
        status = True
        url = self.boot_logos[self.sender().text()]
        index_path = os.path.join(self.combobox_drive.currentText(),"bios","bisrv.asd")
        bootlogo_file = "bootlogo.tmp"
        msgBox = DownloadProgressDialog()
        msgBox.setText("Downloading Boot Logo...")
        msgBox.show()
        msgBox.showProgress(1, True)
        if not tadpole_functions.downloadFileFromGithub(bootlogo_file, url):
            status = False
        if tadpole_functions.changeBootLogo(index_path, bootlogo_file, msgBox):
            QMessageBox.about(self, "Success", "The boot logo was updated to " + self.sender().text())
            status = True
        else:
            QMessageBox.about(self, "Failure", "Something went wrong while trying to change the Boot logo")
            status = True
        os.remove(bootlogo_file)
        return status
    
    def rebuildAll(self):
        RunFrogTool(self.combobox_drive.currentText(),static_AllSystems)
        return

    def createSaveBackup(self):
        drive = self.combobox_drive.currentText()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        QMessageBox.about(self, "Select location",f"Select where you want to save your backup, \
or cancel to save in the same directory as Tadpole.\n\n\
It is recommended to save it somewhere other than your SD card used with the SF2000.")
        path = QFileDialog.getExistingDirectory()
        msgBox = QMessageBox()
        msgBox.setWindowTitle("Creating Save Backup")
        msgBox.setText("Please Wait")
        msgBox.show()
        if path == '':
            savefilename = f"SF2000SaveBackup_{timestamp}.zip"
        else:
            savefilename = os.path.join(path, f"SF2000SaveBackup_{timestamp}.zip")

        if tadpole_functions.createSaveBackup(drive,savefilename):   
            msgBox.close()
            if path == '':
                QMessageBox.about(self, "Success",f"Save backup created in:\n\r{savefilename}, located in the same folder you have Tadpole.")
            else:
                QMessageBox.about(self, "Success",f"Save backup created at:\n\r{savefilename}")
        else:
            msgBox.close()
            QMessageBox.about(self, "Failure","ERROR: Something went wrong while trying to create the save backup")    
        
    def copyRoms(self):
        drive = window.combobox_drive.currentText()
        console = window.combobox_console.currentText()
        #ARCADE is special, only ZIP's are supported
        if(console == 'ARCADE'):          
            filenames, _ = QFileDialog.getOpenFileNames(self,"Select ROMs",'',"ROM files (*.zip *.bkp)")
        else:
            filenames, _ = QFileDialog.getOpenFileNames(self,"Select ROMs",'',"ROM files (*.zip *.bkp \
                                                    *.zfc *.zsf *.zmd *.zgb *.zfb *.smc *.fig *.sfc *.gd3 *.gd7 *.dx2 *.bsx *.swc \
                                                    *.nes *.nfc *.fds *.unf *.gbc *.gb *.sgb *.gba *.agb *.gbz *.bin *.md *.smd *.gen *.sms)")
        if len(filenames) == 0:
            return
        if filenames:
            msgBox = DownloadProgressDialog()
            msgBox.setText(" Copying "+ console + " Roms...")
            games_copied = 1
            msgBox.progress.reset()
            msgBox.progress.setMaximum(len(filenames)+1)
            msgBox.show()
            QApplication.processEvents()
            for filename in filenames:
                games_copied += 1
                msgBox.showProgress(games_copied, True)
                #Additoinal safety to make sure this file exists...
                try: 
                    if os.path.isfile(filename):
                        #Arcade needs the zip file in the /bin folder and we create the ZFB for it
                        if console == 'ARCADE':
                            consolePath = os.path.join(drive, console, 'bin')
                            #Arcade also needs up to create the ZFB as its just the thumbnail + filename
                            tadpole_functions.createZFBFile(drive, '', filename)
                        else:
                            consolePath = os.path.join(drive, console)
                        shutil.copy(filename, consolePath)
                        print (filename + " added to " + consolePath)
                except Exception as e:
                    logging.error("Can't copy because {e}")
                    continue
            msgBox.close()
            qm = QMessageBox
            ret = qm.question(self,'Add Thumbnails?', f"Added " + str(len(filenames)) + " ROMs to " + consolePath + "\n\nDo you want to add thumbnails?\n\n\
Note: You can change in settings to either pick your own or try to downlad automatically.", qm.Yes | qm.No)
            if ret == qm.Yes:
                self.addBoxart()
        RunFrogTool(drive,console)
            
    def validateGameShortcutComboBox(self):
        currentComboBox = self.sender() 
        if currentComboBox.currentText() == '':
            QMessageBox.about(self, "Game Shortcut","You can't really remove a game shortcut slot on SF2000.\n\nIf you don't pick another game, this game will stay as a shortcut when you switch systems or make other changes.")
        else:
            for i in range(self.tbl_gamelist.rowCount()):
                comboBox = self.tbl_gamelist.cellWidget(i, 3)
                if comboBox == currentComboBox:
                    continue
                if comboBox.currentText() == currentComboBox.currentText():
                    QMessageBox.about(self, "Error","You had the shortcut: " + comboBox.currentText() + " assigned to " + window.tbl_gamelist.item(i, 0).text()+ "\nChanging it to the newly selected game.")
                    comboBox.setCurrentIndex(0)
        self.processGameShortcuts()
        return
    
    def addShortcutImages(self):
        drive = self.combobox_drive.currentText()
        console = self.combobox_console.currentText()
        table = self.tbl_gamelist
        dialog = GameShortcutIconsDialog(drive, console, table)
        status = dialog.exec()
        if status:
            QMessageBox.about(self, "Game Shortcuts",f"Updated your game shortcut icons.")
        else:
            print("user cancelled")
        #let's get the temp PNG out if for some reason it didn't get cleaned up
        if os.path.exists('currentBackground.temp.png'):
            os.remove('currentBackground.temp.png')

    def deleteROMs(self):       
        drive = self.combobox_drive.currentText()
        console = self.combobox_console.currentText()
        qm = QMessageBox
        ret = qm.question(self,'Delete ROMs?', "Are you sure you want to delete all selected ROMs?" , qm.Yes | qm.No)
        if ret == qm.No:
            return
        for item in self.tbl_gamelist.selectedItems():
            try:
                objGame = self.ROMList[item.row()]
                if console == 'ARCADE':
                    arcadeZIPROM = tadpole_functions.extractFileNameFromZFB(objGame.ROMlocation)
                    arcadeZIPPath = os.path.join(drive, console, 'bin', arcadeZIPROM)
                    os.remove(arcadeZIPPath)
                os.remove(objGame.ROMlocation)
            except Exception:
                QMessageBox.about(self, "Error","Could not delete ROM.")
        QMessageBox.about(self, "Success",f"Successfully deleted selected ROMs.")
        RunFrogTool(drive,console)

    def copyUserSelectedDirectoryButton(self):
        source_directory = self.combobox_drive.currentText()
        qm = QMessageBox()
        ret = qm.question(self, "Copy?", "Do you want to copy your entire folder over to the SD?\n\n\
                          All files will be overriden, INCLUDING game saves.  Are you sure you want to continue?")
        if ret == qm.No:
            return
        for drive in psutil.disk_partitions():
            # Check that the partition is an Sf2000 SD card
            if(tadpole_functions.checkDriveLooksFroggy(drive.mountpoint)):
                # TODO: what happens if we run out of space?
                # TODO: What happens if we want to write to a drive thats not the first detected froggy drive
                ret = qm.question(self, "SD Card", "Froggy files found on " + drive.mountpoint + "\n\nAre you sure you want to copy and overwrite all files, including saves?")
                if ret == qm.No:
                    return              
                progressMsgBox = DownloadProgressDialog()
                progressMsgBox.setText("Copying files")
                progressMsgBox.show()
                tadpole_functions.copy_files(source_directory, drive.mountpoint, progressMsgBox.progress)
                progressMsgBox.close()
                QMessageBox.about(self, "Success", "Files copied successfully.")
                return
    
    
    #NOTE: this function refreshes the ROM table.  If you run this AND NOT FROG_TOOL, you can get your window out of sync
    #So don't run loadROMsToTable, instead run FrogTool(console)
    def loadROMsToTable(self):
        drive = self.combobox_drive.currentText()
        system = self.combobox_console.currentText()
        print(f"loading roms to table for ({drive}) ({system})")
        logging.info(f"loading roms to table for ({drive}) ({system})")
        msgBox = DownloadProgressDialog()
        msgBox.setText(" Loading "+ system + " ROMS...")
        if drive == static_NoDrives or system == "???" or system == static_AllSystems:
            #TODO: should load ALL ROMs to the table rather than none
            self.tbl_gamelist.setRowCount(0)
            return
        roms_path = os.path.join(drive, system)
        try:
            files = frogtool.getROMList(roms_path)
            self.ROMList = []
            msgBox.progress.reset()
            msgBox.progress.setMaximum(len(files))
            msgBox.show()
            QApplication.processEvents()
            #Disable signals from firing from these changes
            self.tbl_gamelist.cellChanged.disconnect(self.catchTableCellChanged)
            self.tbl_gamelist.setRowCount(len(files))
            print(f"Found {len(files)} ROMs")
            start_time = time.perf_counter()
            #sort the list aphabetically before we go through it
            files = sorted(files)
            for i,game in enumerate(files):
                objGame = sf2000ROM(os.path.join(roms_path, game))
                self.ROMList.append(objGame)
                humanReadableFileSize = tadpole_functions.getHumanReadableFileSize(objGame.getFileSize())
                # Filename
                cell_filename = QTableWidgetItem(f"{objGame.title}")
                cell_filename.setTextAlignment(Qt.AlignVCenter)
                #cell_filename.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                self.tbl_gamelist.setItem(i, 0, cell_filename)  
                #Filesize
                cell_fileSize = QTableWidgetItem(f"{humanReadableFileSize}")
                cell_fileSize.setTextAlignment(Qt.AlignCenter)
                cell_fileSize.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                self.tbl_gamelist.setItem(i, 1, cell_fileSize) 
                # View Thumbnail 
                #Show picture if thumbnails in View is selected
                if tpConf.getViewThumbnailsInTable():
                    # We will use the cell icons to display the thumbnails.
                    # TODO imgrate this to using images instead so we can use icons for other things in future
                    self.tbl_gamelist.setIconSize(QSize(144, 208))
                    cell_viewthumbnail = QTableWidgetItem()
                    cell_viewthumbnail.setTextAlignment(Qt.AlignCenter)
                    #pathToROM = os.path.join(roms_path, game)
                    pathToROM = objGame.ROMlocation
                    extension = Path(pathToROM).suffix
                    #only show thumbnails of the .z** files 
                    sys_zxx_ext = '.' + frogtool.zxx_ext[system]
                    if(extension == sys_zxx_ext):
                        with open(pathToROM, "rb") as rom_file:
                            rom_content = bytearray(rom_file.read(((144*208)*2)))
                        
                        img = QImage(rom_content[0:((144*208)*2)], 144, 208, QImage.Format_RGB16) # The byte array length has been left here as a second safety to ensure we dont try to over read.            
                        pimg = QPixmap()
                        icon = QIcon()
                        QPixmap.convertFromImage(pimg, img)
                        #QIcon.addPixmap(icon, pimg)
                        #cell_viewthumbnail.setIcon(icon)
                        cell_viewthumbnail.setData(Qt.DecorationRole, pimg)
                        cell_viewthumbnail.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                        self.tbl_gamelist.setItem(i, 2, cell_viewthumbnail)
                    else:
                        cell_viewthumbnail = QTableWidgetItem(f"\nNo thumbnail\n Click to edit\n")
                        cell_viewthumbnail.setTextAlignment(Qt.AlignCenter)
                        cell_viewthumbnail.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                        self.tbl_gamelist.setItem(i, 2, cell_viewthumbnail)   
                else:
                    cell_viewthumbnail = QTableWidgetItem(f"View")
                    cell_viewthumbnail.setTextAlignment(Qt.AlignCenter)
                    cell_viewthumbnail.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                    self.tbl_gamelist.setItem(i, 2, cell_viewthumbnail)   
                # Add to Shortcuts-
                shortcut_comboBox = QComboBox()
                shortcut_comboBox.addItem("")
                shortcut_comboBox.addItem("1")
                shortcut_comboBox.addItem("2")
                shortcut_comboBox.addItem("3")
                shortcut_comboBox.addItem("4")
                # set previously saved shortcuts
                position = tadpole_functions.getGameShortcutPosition(drive, system, game)
                shortcut_comboBox.setCurrentIndex(position)
                self.tbl_gamelist.setCellWidget(i, 3, shortcut_comboBox)
                # get a callback to make sure the user isn't setting the same shortcut twice
                shortcut_comboBox.activated.connect(self.validateGameShortcutComboBox)
                # View Delete Button 
                cell_delete = QTableWidgetItem(f"Delete")
                cell_delete.setTextAlignment(Qt.AlignCenter)
                cell_delete.setFlags(Qt.ItemIsSelectable|Qt.ItemIsEnabled)
                self.tbl_gamelist.setItem(i, 4, cell_delete)
                # Update progressbar
                msgBox.showProgress(i, False)
            end_time = time.perf_counter()
            print(f"Image loading time: {end_time - start_time}")
            self.tbl_gamelist.resizeRowsToContents()
            #Restore signals
            self.tbl_gamelist.cellChanged.connect(self.catchTableCellChanged)
            print("finished loading roms to table")    
        except frogtool.StopExecution:
            # Empty the table
            self.tbl_gamelist.setRowCount(0)
            print("frogtool stop execution on table load caught")
        msgBox.close()  
        self.tbl_gamelist.scrollToTop()
        self.tbl_gamelist.show()

    def RebuildClicked(self):
        RunFrogTool(self.combobox_drive.currentText(),self.combobox_console.currentText())
        return
            
if __name__ == "__main__":
    try:
        # Per logger documentation, create logging as soon as possible before other hreads    
        if not os.path.exists(static_TadpoleDir):
            os.mkdir(static_TadpoleDir)
        logging.basicConfig(filename=static_LoggingPath,
                        filemode='a',
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S',
                        level=logging.DEBUG)
        logging.info("Tadpole Started")
        #Setup config
        config = configparser.ConfigParser()
        # Initialise the Application
        app = QApplication(sys.argv)
        # Build the Window
        window = MainWindow()
        window.show()

        # Clear and update the list of consoles. This has to happen before the drive loading in case a valid SD card is already connected
        window.combobox_console.clear()
        for console in tadpole_functions.systems.keys():
            window.combobox_console.addItem(QIcon(), console, console)

        # Update list of drives
        window.combobox_drive.addItem(QIcon(), static_NoDrives, static_NoDrives)
        #Check for Froggy SD cards
        window.reloadDriveList()
        app.exec()
    except Exception as e:
        print(f"ERROR: An Exception occurred. {e}")
        logging.exception("main crashed. Error: %s", e)
