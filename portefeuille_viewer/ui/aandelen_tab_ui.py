# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'aandelen_tab.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSizePolicy, QSpacerItem,
    QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

class Ui_AandelenTab(object):
    def setupUi(self, AandelenTab):
        if not AandelenTab.objectName():
            AandelenTab.setObjectName(u"AandelenTab")
        AandelenTab.resize(1200, 800)
        self.verticalLayout_main = QVBoxLayout(AandelenTab)
        self.verticalLayout_main.setObjectName(u"verticalLayout_main")
        self.layoutButtons = QHBoxLayout()
        self.layoutButtons.setObjectName(u"layoutButtons")
        self.btnSelecteerBrokers = QPushButton(AandelenTab)
        self.btnSelecteerBrokers.setObjectName(u"btnSelecteerBrokers")
        self.btnSelecteerBrokers.setStyleSheet(u"background-color: rgb(224, 240, 255);")

        self.layoutButtons.addWidget(self.btnSelecteerBrokers)

        self.btnWisFilters = QPushButton(AandelenTab)
        self.btnWisFilters.setObjectName(u"btnWisFilters")
        self.btnWisFilters.setStyleSheet(u"background-color: rgb(255, 224, 224);")

        self.layoutButtons.addWidget(self.btnWisFilters)

        self.btnExportExcel = QPushButton(AandelenTab)
        self.btnExportExcel.setObjectName(u"btnExportExcel")
        self.btnExportExcel.setStyleSheet(u"background-color: rgb(228, 255, 217);")

        self.layoutButtons.addWidget(self.btnExportExcel)

        self.lblLiveTicker = QLabel(AandelenTab)
        self.lblLiveTicker.setObjectName(u"lblLiveTicker")

        self.layoutButtons.addWidget(self.lblLiveTicker)

        self.spacerBtns = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.layoutButtons.addItem(self.spacerBtns)


        self.verticalLayout_main.addLayout(self.layoutButtons)

        self.tblAandelen = QTableView(AandelenTab)
        self.tblAandelen.setObjectName(u"tblAandelen")
        self.tblAandelen.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblAandelen.setAlternatingRowColors(True)
        self.tblAandelen.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.verticalLayout_main.addWidget(self.tblAandelen)

        self.tblTotalen = QTableWidget(AandelenTab)
        if (self.tblTotalen.columnCount() < 16):
            self.tblTotalen.setColumnCount(16)
        if (self.tblTotalen.rowCount() < 1):
            self.tblTotalen.setRowCount(1)
        self.tblTotalen.setObjectName(u"tblTotalen")
        self.tblTotalen.setRowCount(1)
        self.tblTotalen.setColumnCount(16)

        self.verticalLayout_main.addWidget(self.tblTotalen)


        self.retranslateUi(AandelenTab)

        QMetaObject.connectSlotsByName(AandelenTab)
    # setupUi

    def retranslateUi(self, AandelenTab):
        self.btnSelecteerBrokers.setText(QCoreApplication.translate("AandelenTab", u"Selecteer brokers", None))
        self.btnWisFilters.setText(QCoreApplication.translate("AandelenTab", u"Wis filters", None))
        self.btnExportExcel.setText(QCoreApplication.translate("AandelenTab", u"Excel snapshot", None))
        self.lblLiveTicker.setText(QCoreApplication.translate("AandelenTab", u"TextLabel", None))
        pass
    # retranslateUi

