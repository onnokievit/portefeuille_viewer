# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab3_C.ui'
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
        self.priceAantalChart = PlotWidget(self.widget)
        self.priceAantalChart.setObjectName(u"priceAantalChart")
        self.priceAantalChart.setGeometry(QRect(4, 680, 401, 121))
        self.verticalLayout_7 = QVBoxLayout(self.priceAantalChart)
        self.verticalLayout_7.setSpacing(9)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.verticalLayout_7.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_4 = QWidget(self.widget)
        self.verticalLayoutWidget_4.setObjectName(u"verticalLayoutWidget_4")
        self.verticalLayoutWidget_4.setGeometry(QRect(60, 820, 711, 261))
        self.verticalLayout_6 = QVBoxLayout(self.verticalLayoutWidget_4)
        self.verticalLayout_6.setSpacing(2)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.verticalLayout_6.setContentsMargins(2, 2, 2, 2)
        self.resultaatChart = PlotWidget(self.widget)
        self.resultaatChart.setObjectName(u"resultaatChart")
        self.resultaatChart.setGeometry(QRect(410, 680, 411, 121))
        self.verticalLayout_9 = QVBoxLayout(self.resultaatChart)
        self.verticalLayout_9.setSpacing(9)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.verticalLayout_9.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_5 = QWidget(self.widget)
        self.verticalLayoutWidget_5.setObjectName(u"verticalLayoutWidget_5")
        self.verticalLayoutWidget_5.setGeometry(QRect(830, 550, 711, 121))
        self.verticalLayout_8 = QVBoxLayout(self.verticalLayoutWidget_5)
        self.verticalLayout_8.setSpacing(2)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.verticalLayout_8.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpenCall = QTableView(self.verticalLayoutWidget_5)
        self.tableViewOptiesOpenCall.setObjectName(u"tableViewOptiesOpenCall")

        self.verticalLayout_8.addWidget(self.tableViewOptiesOpenCall)

        self.verticalLayoutWidget_6 = QWidget(self.widget)
        self.verticalLayoutWidget_6.setObjectName(u"verticalLayoutWidget_6")
        self.verticalLayoutWidget_6.setGeometry(QRect(830, 680, 711, 121))
        self.verticalLayout_10 = QVBoxLayout(self.verticalLayoutWidget_6)
        self.verticalLayout_10.setSpacing(2)
        self.verticalLayout_10.setObjectName(u"verticalLayout_10")
        self.verticalLayout_10.setContentsMargins(2, 2, 2, 2)
        self.tableViewOptiesOpenPut = QTableView(self.verticalLayoutWidget_6)
        self.tableViewOptiesOpenPut.setObjectName(u"tableViewOptiesOpenPut")

        self.verticalLayout_10.addWidget(self.tableViewOptiesOpenPut)

        self.horizontalLayoutWidget = QWidget(self.widget)
        self.horizontalLayoutWidget.setObjectName(u"horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(10, 0, 801, 31))
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

        self.comboBoxStatus = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxStatus.setObjectName(u"comboBoxStatus")
        self.comboBoxStatus.setMaximumSize(QSize(80, 16777215))

        self.horizontalLayout.addWidget(self.comboBoxStatus)

        self.comboBoxValueGrow = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxValueGrow.setObjectName(u"comboBoxValueGrow")
        self.comboBoxValueGrow.setMaximumSize(QSize(80, 16777215))

        self.horizontalLayout.addWidget(self.comboBoxValueGrow)

        self.comboBoxSector = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxSector.setObjectName(u"comboBoxSector")
        self.comboBoxSector.setMaximumSize(QSize(140, 16777215))

        self.horizontalLayout.addWidget(self.comboBoxSector)

        self.comboBoxRegio = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxRegio.setObjectName(u"comboBoxRegio")
        self.comboBoxRegio.setMaximumSize(QSize(60, 16777215))

        self.horizontalLayout.addWidget(self.comboBoxRegio)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.horizontalLayoutWidget_2 = QWidget(self.widget)
        self.horizontalLayoutWidget_2.setObjectName(u"horizontalLayoutWidget_2")
        self.horizontalLayoutWidget_2.setGeometry(QRect(830, 0, 711, 31))
        self.horizontalLayout_2 = QHBoxLayout(self.horizontalLayoutWidget_2)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.lineEditFilterOptiesOpen = QLineEdit(self.horizontalLayoutWidget_2)
        self.lineEditFilterOptiesOpen.setObjectName(u"lineEditFilterOptiesOpen")
        self.lineEditFilterOptiesOpen.setMinimumSize(QSize(300, 24))
        self.lineEditFilterOptiesOpen.setMaximumSize(QSize(450, 16777215))

        self.horizontalLayout_2.addWidget(self.lineEditFilterOptiesOpen, 0, Qt.AlignmentFlag.AlignLeft)

        self.buttonClearFiltersOptiesOpen = QPushButton(self.horizontalLayoutWidget_2)
        self.buttonClearFiltersOptiesOpen.setObjectName(u"buttonClearFiltersOptiesOpen")
        self.buttonClearFiltersOptiesOpen.setMaximumSize(QSize(150, 16777215))

        self.horizontalLayout_2.addWidget(self.buttonClearFiltersOptiesOpen, 0, Qt.AlignmentFlag.AlignRight)

        self.verticalLayoutWidget_7 = QWidget(self.widget)
        self.verticalLayoutWidget_7.setObjectName(u"verticalLayoutWidget_7")
        self.verticalLayoutWidget_7.setGeometry(QRect(830, 310, 711, 121))
        self.verticalLayout_11 = QVBoxLayout(self.verticalLayoutWidget_7)
        self.verticalLayout_11.setSpacing(2)
        self.verticalLayout_11.setObjectName(u"verticalLayout_11")
        self.verticalLayout_11.setContentsMargins(2, 2, 2, 2)
        self.tableViewAandelen = QTableView(self.verticalLayoutWidget_7)
        self.tableViewAandelen.setObjectName(u"tableViewAandelen")

        self.verticalLayout_11.addWidget(self.tableViewAandelen)

        self.verticalLayoutWidget_8 = QWidget(self.widget)
        self.verticalLayoutWidget_8.setObjectName(u"verticalLayoutWidget_8")
        self.verticalLayoutWidget_8.setGeometry(QRect(830, 440, 711, 101))
        self.verticalLayout_12 = QVBoxLayout(self.verticalLayoutWidget_8)
        self.verticalLayout_12.setSpacing(2)
        self.verticalLayout_12.setObjectName(u"verticalLayout_12")
        self.verticalLayout_12.setContentsMargins(2, 2, 2, 2)
        self.tableViewSprinters = QTableView(self.verticalLayoutWidget_8)
        self.tableViewSprinters.setObjectName(u"tableViewSprinters")

        self.verticalLayout_12.addWidget(self.tableViewSprinters)

        self.verticalLayoutWidget_3 = QWidget(self.widget)
        self.verticalLayoutWidget_3.setObjectName(u"verticalLayoutWidget_3")
        self.verticalLayoutWidget_3.setGeometry(QRect(6, 310, 811, 361))
        self.layoutChart = QVBoxLayout(self.verticalLayoutWidget_3)
        self.layoutChart.setSpacing(10)
        self.layoutChart.setObjectName(u"layoutChart")
        self.layoutChart.setContentsMargins(0, 0, 0, 0)
        self.payoff_table = QTableWidget(self.widget)
        self.payoff_table.setObjectName(u"payoff_table")
        self.payoff_table.setGeometry(QRect(6, 40, 811, 257))
        self.payoff_table.verticalHeader().setMinimumSectionSize(30)
        self.tableViewOptiesOpen = QTableView(self.widget)
        self.tableViewOptiesOpen.setObjectName(u"tableViewOptiesOpen")
        self.tableViewOptiesOpen.setGeometry(QRect(830, 40, 707, 257))

        self.verticalLayout_2.addWidget(self.widget)


        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.buttonClearFiltersOptiesOpen.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Clear Filter", None))
    # retranslateUi

