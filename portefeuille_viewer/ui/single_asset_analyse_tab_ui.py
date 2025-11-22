# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab3_B.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QDoubleSpinBox,
    QHeaderView, QPushButton, QSizePolicy, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1727, 997)
        self.verticalLayout_2 = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.widget = QWidget(SingleAssetAnalyseTab)
        self.widget.setObjectName(u"widget")
        self.widget_2 = QWidget(self.widget)
        self.widget_2.setObjectName(u"widget_2")
        self.widget_2.setGeometry(QRect(0, 0, 900, 500))
        self.verticalLayout_3 = QVBoxLayout(self.widget_2)
        self.verticalLayout_3.setSpacing(0)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout_4 = QVBoxLayout()
        self.verticalLayout_4.setSpacing(0)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.payoff_table = QTableWidget(self.widget_2)
        self.payoff_table.setObjectName(u"payoff_table")

        self.verticalLayout_4.addWidget(self.payoff_table)

        self.layoutChart = QVBoxLayout()
        self.layoutChart.setSpacing(0)
        self.layoutChart.setObjectName(u"layoutChart")

        self.verticalLayout_4.addLayout(self.layoutChart)

        self.verticalLayout_4.setStretch(0, 2)
        self.verticalLayout_4.setStretch(1, 2)

        self.verticalLayout.addLayout(self.verticalLayout_4)


        self.verticalLayout_3.addLayout(self.verticalLayout)

        self.priceAantalChart = PlotWidget(self.widget)
        self.priceAantalChart.setObjectName(u"priceAantalChart")
        self.priceAantalChart.setGeometry(QRect(0, 520, 450, 231))
        self.verticalLayout_7 = QVBoxLayout(self.priceAantalChart)
        self.verticalLayout_7.setSpacing(9)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.verticalLayout_7.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_4 = QWidget(self.widget)
        self.verticalLayoutWidget_4.setObjectName(u"verticalLayoutWidget_4")
        self.verticalLayoutWidget_4.setGeometry(QRect(900, 0, 821, 251))
        self.verticalLayout_6 = QVBoxLayout(self.verticalLayoutWidget_4)
        self.verticalLayout_6.setSpacing(2)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.verticalLayout_6.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpen = QTableView(self.verticalLayoutWidget_4)
        self.tableViewOptiesOpen.setObjectName(u"tableViewOptiesOpen")

        self.verticalLayout_6.addWidget(self.tableViewOptiesOpen)

        self.resultaatChart = PlotWidget(self.widget)
        self.resultaatChart.setObjectName(u"resultaatChart")
        self.resultaatChart.setGeometry(QRect(450, 520, 450, 231))
        self.verticalLayout_9 = QVBoxLayout(self.resultaatChart)
        self.verticalLayout_9.setSpacing(9)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.verticalLayout_9.setContentsMargins(9, 9, 9, 9)
        self.asset_selector = QComboBox(self.widget)
        self.asset_selector.setObjectName(u"asset_selector")
        self.asset_selector.setGeometry(QRect(940, 300, 150, 24))
        self.asset_selector.setMaximumSize(QSize(150, 16777215))
        self.stepSizeBox = QDoubleSpinBox(self.widget)
        self.stepSizeBox.setObjectName(u"stepSizeBox")
        self.stepSizeBox.setGeometry(QRect(940, 340, 80, 23))
        self.stepSizeBox.setMaximumSize(QSize(80, 16777215))
        self.stepSizeBox.setDecimals(6)
        self.stepSizeBox.setValue(0.020000000000000)
        self.startDate = QDateEdit(self.widget)
        self.startDate.setObjectName(u"startDate")
        self.startDate.setGeometry(QRect(940, 380, 120, 23))
        self.startDate.setMaximumSize(QSize(120, 16777215))
        self.startDate.setCalendarPopup(True)
        self.endDate = QDateEdit(self.widget)
        self.endDate.setObjectName(u"endDate")
        self.endDate.setGeometry(QRect(940, 420, 120, 23))
        self.endDate.setMaximumSize(QSize(120, 16777215))
        self.endDate.setCalendarPopup(True)
        self.pushButton = QPushButton(self.widget)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(950, 470, 75, 24))
        self.pushButton.setMaximumSize(QSize(75, 16777215))

        self.verticalLayout_2.addWidget(self.widget)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"PushButton", None))
    # retranslateUi

