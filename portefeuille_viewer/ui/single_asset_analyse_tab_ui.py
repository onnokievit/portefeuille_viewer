# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QSizePolicy, QSpacerItem, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1097, 700)
        self.verticalLayout_main = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_main.setObjectName(u"verticalLayout_main")
        self.layoutSelector = QHBoxLayout()
        self.layoutSelector.setObjectName(u"layoutSelector")
        self.lblAsset = QLabel(SingleAssetAnalyseTab)
        self.lblAsset.setObjectName(u"lblAsset")

        self.layoutSelector.addWidget(self.lblAsset)

        self.asset_selector = QComboBox(SingleAssetAnalyseTab)
        self.asset_selector.setObjectName(u"asset_selector")

        self.layoutSelector.addWidget(self.asset_selector)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.layoutSelector.addItem(self.horizontalSpacer)


        self.verticalLayout_main.addLayout(self.layoutSelector)

        self.splitter = QSplitter(SingleAssetAnalyseTab)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.chartWidget = QWidget(self.splitter)
        self.chartWidget.setObjectName(u"chartWidget")
        self.chartWidget.setMinimumSize(QSize(100, 200))
        self.layoutChart = QVBoxLayout(self.chartWidget)
        self.layoutChart.setObjectName(u"layoutChart")
        self.layoutChart.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(self.chartWidget)
        self.payoff_table = QTableWidget(self.splitter)
        self.payoff_table.setObjectName(u"payoff_table")
        self.payoff_table.setRowCount(0)
        self.payoff_table.setColumnCount(0)
        self.splitter.addWidget(self.payoff_table)
        self.payoff_table.horizontalHeader().setStretchLastSection(True)
        self.payoff_table.verticalHeader().setMinimumSectionSize(22)
        self.payoff_table.verticalHeader().setDefaultSectionSize(25)

        self.verticalLayout_main.addWidget(self.splitter)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        self.lblAsset.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Asset:", None))
        pass
    # retranslateUi

