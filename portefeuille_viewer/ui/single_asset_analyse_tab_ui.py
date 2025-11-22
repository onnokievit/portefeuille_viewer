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
    QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTableView, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1686, 1089)
        self.verticalLayout_2 = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.widget = QWidget(SingleAssetAnalyseTab)
        self.widget.setObjectName(u"widget")
        self.widget_2 = QWidget(self.widget)
        self.widget_2.setObjectName(u"widget_2")
        self.widget_2.setGeometry(QRect(0, 40, 900, 701))
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
        self.layoutChart.setSpacing(10)
        self.layoutChart.setObjectName(u"layoutChart")

        self.verticalLayout_4.addLayout(self.layoutChart)

        self.verticalLayout_4.setStretch(0, 62)
        self.verticalLayout_4.setStretch(1, 100)

        self.verticalLayout.addLayout(self.verticalLayout_4)


        self.verticalLayout_3.addLayout(self.verticalLayout)

        self.priceAantalChart = PlotWidget(self.widget)
        self.priceAantalChart.setObjectName(u"priceAantalChart")
        self.priceAantalChart.setGeometry(QRect(0, 750, 445, 161))
        self.verticalLayout_7 = QVBoxLayout(self.priceAantalChart)
        self.verticalLayout_7.setSpacing(9)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.verticalLayout_7.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_4 = QWidget(self.widget)
        self.verticalLayoutWidget_4.setObjectName(u"verticalLayoutWidget_4")
        self.verticalLayoutWidget_4.setGeometry(QRect(910, 40, 751, 271))
        self.verticalLayout_6 = QVBoxLayout(self.verticalLayoutWidget_4)
        self.verticalLayout_6.setSpacing(2)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.verticalLayout_6.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpen = QTableView(self.verticalLayoutWidget_4)
        self.tableViewOptiesOpen.setObjectName(u"tableViewOptiesOpen")

        self.verticalLayout_6.addWidget(self.tableViewOptiesOpen)

        self.resultaatChart = PlotWidget(self.widget)
        self.resultaatChart.setObjectName(u"resultaatChart")
        self.resultaatChart.setGeometry(QRect(450, 750, 451, 161))
        self.verticalLayout_9 = QVBoxLayout(self.resultaatChart)
        self.verticalLayout_9.setSpacing(9)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.verticalLayout_9.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_5 = QWidget(self.widget)
        self.verticalLayoutWidget_5.setObjectName(u"verticalLayoutWidget_5")
        self.verticalLayoutWidget_5.setGeometry(QRect(910, 660, 751, 121))
        self.verticalLayout_8 = QVBoxLayout(self.verticalLayoutWidget_5)
        self.verticalLayout_8.setSpacing(2)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.verticalLayout_8.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpenCall = QTableView(self.verticalLayoutWidget_5)
        self.tableViewOptiesOpenCall.setObjectName(u"tableViewOptiesOpenCall")

        self.verticalLayout_8.addWidget(self.tableViewOptiesOpenCall)

        self.verticalLayoutWidget_6 = QWidget(self.widget)
        self.verticalLayoutWidget_6.setObjectName(u"verticalLayoutWidget_6")
        self.verticalLayoutWidget_6.setGeometry(QRect(910, 790, 751, 121))
        self.verticalLayout_10 = QVBoxLayout(self.verticalLayoutWidget_6)
        self.verticalLayout_10.setSpacing(2)
        self.verticalLayout_10.setObjectName(u"verticalLayout_10")
        self.verticalLayout_10.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpenPut = QTableView(self.verticalLayoutWidget_6)
        self.tableViewOptiesOpenPut.setObjectName(u"tableViewOptiesOpenPut")

        self.verticalLayout_10.addWidget(self.tableViewOptiesOpenPut)

        self.horizontalLayoutWidget = QWidget(self.widget)
        self.horizontalLayoutWidget.setObjectName(u"horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(0, 0, 901, 31))
        self.horizontalLayout = QHBoxLayout(self.horizontalLayoutWidget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.asset_selector = QComboBox(self.horizontalLayoutWidget)
        self.asset_selector.setObjectName(u"asset_selector")
        self.asset_selector.setMaximumSize(QSize(150, 16777215))

        self.horizontalLayout.addWidget(self.asset_selector, 0, Qt.AlignmentFlag.AlignLeft)

        self.stepSizeBox = QDoubleSpinBox(self.horizontalLayoutWidget)
        self.stepSizeBox.setObjectName(u"stepSizeBox")
        self.stepSizeBox.setMaximumSize(QSize(80, 16777215))
        self.stepSizeBox.setDecimals(6)
        self.stepSizeBox.setValue(0.020000000000000)

        self.horizontalLayout.addWidget(self.stepSizeBox, 0, Qt.AlignmentFlag.AlignLeft)

        self.startDate = QDateEdit(self.horizontalLayoutWidget)
        self.startDate.setObjectName(u"startDate")
        self.startDate.setMaximumSize(QSize(120, 16777215))
        self.startDate.setCalendarPopup(True)

        self.horizontalLayout.addWidget(self.startDate, 0, Qt.AlignmentFlag.AlignLeft)

        self.endDate = QDateEdit(self.horizontalLayoutWidget)
        self.endDate.setObjectName(u"endDate")
        self.endDate.setMaximumSize(QSize(120, 16777215))
        self.endDate.setCalendarPopup(True)

        self.horizontalLayout.addWidget(self.endDate, 0, Qt.AlignmentFlag.AlignLeft)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.horizontalLayoutWidget_2 = QWidget(self.widget)
        self.horizontalLayoutWidget_2.setObjectName(u"horizontalLayoutWidget_2")
        self.horizontalLayoutWidget_2.setGeometry(QRect(910, 0, 751, 31))
        self.horizontalLayout_2 = QHBoxLayout(self.horizontalLayoutWidget_2)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.lineEditFilterOptiesOpen = QLineEdit(self.horizontalLayoutWidget_2)
        self.lineEditFilterOptiesOpen.setObjectName(u"lineEditFilterOptiesOpen")
        self.lineEditFilterOptiesOpen.setMinimumSize(QSize(300, 0))
        self.lineEditFilterOptiesOpen.setMaximumSize(QSize(450, 16777215))

        self.horizontalLayout_2.addWidget(self.lineEditFilterOptiesOpen, 0, Qt.AlignmentFlag.AlignLeft)

        self.buttonClearFiltersOptiesOpen = QPushButton(self.horizontalLayoutWidget_2)
        self.buttonClearFiltersOptiesOpen.setObjectName(u"buttonClearFiltersOptiesOpen")
        self.buttonClearFiltersOptiesOpen.setMaximumSize(QSize(150, 16777215))

        self.horizontalLayout_2.addWidget(self.buttonClearFiltersOptiesOpen, 0, Qt.AlignmentFlag.AlignRight)


        self.verticalLayout_2.addWidget(self.widget)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.buttonClearFiltersOptiesOpen.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Clear Filter", None))
    # retranslateUi

