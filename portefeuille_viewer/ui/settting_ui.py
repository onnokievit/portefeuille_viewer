# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'settings.ui'
##
## Created by: Qt User Interface Compiler version 6.9.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

class Ui_SettingsTab(object):
    def setupUi(self, SettingsTab):
        if not SettingsTab.objectName():
            SettingsTab.setObjectName(u"SettingsTab")
        SettingsTab.resize(1279, 600)
        self.verticalLayout_main = QVBoxLayout(SettingsTab)
        self.verticalLayout_main.setObjectName(u"verticalLayout_main")
        self.grpEURUSD = QGroupBox(SettingsTab)
        self.grpEURUSD.setObjectName(u"grpEURUSD")
        self.layoutEURUSD = QHBoxLayout(self.grpEURUSD)
        self.layoutEURUSD.setObjectName(u"layoutEURUSD")
        self.lblEURUSD = QLabel(self.grpEURUSD)
        self.lblEURUSD.setObjectName(u"lblEURUSD")

        self.layoutEURUSD.addWidget(self.lblEURUSD)

        self.txtEURUSD = QLineEdit(self.grpEURUSD)
        self.txtEURUSD.setObjectName(u"txtEURUSD")

        self.layoutEURUSD.addWidget(self.txtEURUSD)

        self.btnSaveEURUSD = QPushButton(self.grpEURUSD)
        self.btnSaveEURUSD.setObjectName(u"btnSaveEURUSD")

        self.layoutEURUSD.addWidget(self.btnSaveEURUSD)


        self.verticalLayout_main.addWidget(self.grpEURUSD)

        self.grpIB = QGroupBox(SettingsTab)
        self.grpIB.setObjectName(u"grpIB")
        self.layoutIB = QGridLayout(self.grpIB)
        self.layoutIB.setObjectName(u"layoutIB")
        self.lblIBHost = QLabel(self.grpIB)
        self.lblIBHost.setObjectName(u"lblIBHost")

        self.layoutIB.addWidget(self.lblIBHost, 0, 0, 1, 1)

        self.txtIBHost = QLineEdit(self.grpIB)
        self.txtIBHost.setObjectName(u"txtIBHost")

        self.layoutIB.addWidget(self.txtIBHost, 0, 1, 1, 1)

        self.lblIBPort = QLabel(self.grpIB)
        self.lblIBPort.setObjectName(u"lblIBPort")

        self.layoutIB.addWidget(self.lblIBPort, 1, 0, 1, 1)

        self.txtIBPort = QLineEdit(self.grpIB)
        self.txtIBPort.setObjectName(u"txtIBPort")

        self.layoutIB.addWidget(self.txtIBPort, 1, 1, 1, 1)

        self.btnSaveIB = QPushButton(self.grpIB)
        self.btnSaveIB.setObjectName(u"btnSaveIB")

        self.layoutIB.addWidget(self.btnSaveIB, 0, 2, 2, 1)


        self.verticalLayout_main.addWidget(self.grpIB)

        self.grpDatabase = QGroupBox(SettingsTab)
        self.grpDatabase.setObjectName(u"grpDatabase")
        self.layoutDatabase = QVBoxLayout(self.grpDatabase)
        self.layoutDatabase.setObjectName(u"layoutDatabase")
        self.tblDatabaseConfig = QTableWidget(self.grpDatabase)
        if (self.tblDatabaseConfig.columnCount() < 5):
            self.tblDatabaseConfig.setColumnCount(5)
        __qtablewidgetitem = QTableWidgetItem()
        self.tblDatabaseConfig.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.tblDatabaseConfig.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.tblDatabaseConfig.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.tblDatabaseConfig.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.tblDatabaseConfig.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        self.tblDatabaseConfig.setObjectName(u"tblDatabaseConfig")

        self.layoutDatabase.addWidget(self.tblDatabaseConfig)

        self.layoutButtons = QHBoxLayout()
        self.layoutButtons.setObjectName(u"layoutButtons")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.layoutButtons.addItem(self.horizontalSpacer)

        self.btnNewDatabase = QPushButton(self.grpDatabase)
        self.btnNewDatabase.setObjectName(u"btnNewDatabase")

        self.layoutButtons.addWidget(self.btnNewDatabase)


        self.layoutDatabase.addLayout(self.layoutButtons)


        self.verticalLayout_main.addWidget(self.grpDatabase)


        self.retranslateUi(SettingsTab)

        QMetaObject.connectSlotsByName(SettingsTab)
    # setupUi

    def retranslateUi(self, SettingsTab):
        self.grpEURUSD.setTitle(QCoreApplication.translate("SettingsTab", u"EUR/USD Instelling", None))
        self.lblEURUSD.setText(QCoreApplication.translate("SettingsTab", u"EUR/USD:", None))
        self.btnSaveEURUSD.setText(QCoreApplication.translate("SettingsTab", u"EUR/USD Opslaan", None))
        self.grpIB.setTitle(QCoreApplication.translate("SettingsTab", u"Interactive Brokers Instellingen", None))
        self.lblIBHost.setText(QCoreApplication.translate("SettingsTab", u"IB Host:", None))
        self.txtIBHost.setText(QCoreApplication.translate("SettingsTab", u"127.0.0.1", None))
        self.lblIBPort.setText(QCoreApplication.translate("SettingsTab", u"IB Port:", None))
        self.txtIBPort.setText(QCoreApplication.translate("SettingsTab", u"7496", None))
        self.btnSaveIB.setText(QCoreApplication.translate("SettingsTab", u"IB Instellingen Opslaan", None))
        self.grpDatabase.setTitle(QCoreApplication.translate("SettingsTab", u"Database Configuratie", None))
        ___qtablewidgetitem = self.tblDatabaseConfig.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("SettingsTab", u"Database", None));
        ___qtablewidgetitem1 = self.tblDatabaseConfig.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("SettingsTab", u"Pad", None));
        ___qtablewidgetitem2 = self.tblDatabaseConfig.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("SettingsTab", u"Tekst", None));
        ___qtablewidgetitem3 = self.tblDatabaseConfig.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("SettingsTab", u"Achtergrond", None));
        ___qtablewidgetitem4 = self.tblDatabaseConfig.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("SettingsTab", u"Acties", None));
        self.btnNewDatabase.setText(QCoreApplication.translate("SettingsTab", u"+ Nieuwe Database", None))
        pass
    # retranslateUi

