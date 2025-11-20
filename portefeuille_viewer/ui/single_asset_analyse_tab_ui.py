# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab3.ui'
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
    QGridLayout, QHBoxLayout, QHeaderView, QPushButton,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1633, 1161)
        self.verticalLayout_5 = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.verticalLayout_4 = QVBoxLayout()
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.asset_selector = QComboBox(SingleAssetAnalyseTab)
        self.asset_selector.setObjectName(u"asset_selector")
        self.asset_selector.setMaximumSize(QSize(200, 16777215))

        self.horizontalLayout_3.addWidget(self.asset_selector)

        self.stepSizeBox = QDoubleSpinBox(SingleAssetAnalyseTab)
        self.stepSizeBox.setObjectName(u"stepSizeBox")
        self.stepSizeBox.setMaximumSize(QSize(80, 16777215))
        self.stepSizeBox.setDecimals(3)
        self.stepSizeBox.setValue(0.020000000000000)

        self.horizontalLayout_3.addWidget(self.stepSizeBox)

        self.startDate = QDateEdit(SingleAssetAnalyseTab)
        self.startDate.setObjectName(u"startDate")
        self.startDate.setMaximumSize(QSize(120, 16777215))
        self.startDate.setCalendarPopup(True)

        self.horizontalLayout_3.addWidget(self.startDate)

        self.endDate = QDateEdit(SingleAssetAnalyseTab)
        self.endDate.setObjectName(u"endDate")
        self.endDate.setMaximumSize(QSize(120, 16777215))
        self.endDate.setCalendarPopup(True)

        self.horizontalLayout_3.addWidget(self.endDate)

        self.pushButton = QPushButton(SingleAssetAnalyseTab)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setMaximumSize(QSize(75, 16777215))

        self.horizontalLayout_3.addWidget(self.pushButton, 0, Qt.AlignmentFlag.AlignRight)


        self.verticalLayout_4.addLayout(self.horizontalLayout_3)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.layoutChart1 = QVBoxLayout()
        self.layoutChart1.setObjectName(u"layoutChart1")

        self.gridLayout_2.addLayout(self.layoutChart1, 2, 0, 1, 1)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.widget = QWidget(SingleAssetAnalyseTab)
        self.widget.setObjectName(u"widget")

        self.verticalLayout.addWidget(self.widget)

        self.priceAantalChart = QWidget(SingleAssetAnalyseTab)
        self.priceAantalChart.setObjectName(u"priceAantalChart")

        self.verticalLayout.addWidget(self.priceAantalChart)

        self.resultaatChart = QWidget(SingleAssetAnalyseTab)
        self.resultaatChart.setObjectName(u"resultaatChart")

        self.verticalLayout.addWidget(self.resultaatChart)

        self.verticalLayout.setStretch(0, 4)
        self.verticalLayout.setStretch(1, 2)
        self.verticalLayout.setStretch(2, 2)

        self.gridLayout_2.addLayout(self.verticalLayout, 1, 1, 1, 1)

        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.payoff_table = QTableWidget(SingleAssetAnalyseTab)
        self.payoff_table.setObjectName(u"payoff_table")

        self.verticalLayout_3.addWidget(self.payoff_table)


        self.verticalLayout_2.addLayout(self.verticalLayout_3)

        self.layoutChart = QVBoxLayout()
        self.layoutChart.setObjectName(u"layoutChart")

        self.verticalLayout_2.addLayout(self.layoutChart)

        self.verticalLayout_2.setStretch(0, 1)
        self.verticalLayout_2.setStretch(1, 1)

        self.gridLayout_2.addLayout(self.verticalLayout_2, 1, 0, 1, 1)

        self.gridLayout_2.setColumnStretch(0, 4)
        self.gridLayout_2.setColumnStretch(1, 2)

        self.verticalLayout_4.addLayout(self.gridLayout_2)


        self.verticalLayout_5.addLayout(self.verticalLayout_4)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"PushButton", None))
    # retranslateUi

