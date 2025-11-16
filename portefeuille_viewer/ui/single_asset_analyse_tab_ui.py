# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab1.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QGridLayout,
    QHBoxLayout, QHeaderView, QPushButton, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1617, 1021)
        self.verticalLayout_5 = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.verticalLayout_4 = QVBoxLayout()
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.asset_selector = QComboBox(SingleAssetAnalyseTab)
        self.asset_selector.setObjectName(u"asset_selector")

        self.horizontalLayout_3.addWidget(self.asset_selector)

        self.stepSizeBox = QDoubleSpinBox(SingleAssetAnalyseTab)
        self.stepSizeBox.setObjectName(u"stepSizeBox")
        self.stepSizeBox.setDecimals(3)
        self.stepSizeBox.setValue(0.020000000000000)

        self.horizontalLayout_3.addWidget(self.stepSizeBox)

        self.pushButton = QPushButton(SingleAssetAnalyseTab)
        self.pushButton.setObjectName(u"pushButton")

        self.horizontalLayout_3.addWidget(self.pushButton)


        self.verticalLayout_4.addLayout(self.horizontalLayout_3)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.layoutChart = QVBoxLayout()
        self.layoutChart.setObjectName(u"layoutChart")

        self.gridLayout_2.addLayout(self.layoutChart, 0, 0, 1, 1)

        self.payoff_table_2 = QTableWidget(SingleAssetAnalyseTab)
        self.payoff_table_2.setObjectName(u"payoff_table_2")

        self.gridLayout_2.addWidget(self.payoff_table_2, 1, 1, 1, 1)

        self.payoff_table = QTableWidget(SingleAssetAnalyseTab)
        self.payoff_table.setObjectName(u"payoff_table")

        self.gridLayout_2.addWidget(self.payoff_table, 1, 0, 1, 1)

        self.verticalLayout_6 = QVBoxLayout()
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")

        self.gridLayout_2.addLayout(self.verticalLayout_6, 0, 1, 1, 1)


        self.verticalLayout_4.addLayout(self.gridLayout_2)


        self.verticalLayout_5.addLayout(self.verticalLayout_4)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"PushButton", None))
    # retranslateUi

