# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'single_asset_analyse_tab3_G.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateEdit,
    QDoubleSpinBox, QHBoxLayout, QHeaderView, QLineEdit,
    QPushButton, QSizePolicy, QSpacerItem, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from pyqtgraph import PlotWidget

class Ui_SingleAssetAnalyseTab(object):
    def setupUi(self, SingleAssetAnalyseTab):
        if not SingleAssetAnalyseTab.objectName():
            SingleAssetAnalyseTab.setObjectName(u"SingleAssetAnalyseTab")
        SingleAssetAnalyseTab.resize(1947, 1326)
        self.verticalLayout_2 = QVBoxLayout(SingleAssetAnalyseTab)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.widget = QWidget(SingleAssetAnalyseTab)
        self.widget.setObjectName(u"widget")
        self.priceAantalChart = PlotWidget(self.widget)
        self.priceAantalChart.setObjectName(u"priceAantalChart")
        self.priceAantalChart.setGeometry(QRect(10, 760, 811, 191))
        self.verticalLayout_7 = QVBoxLayout(self.priceAantalChart)
        self.verticalLayout_7.setSpacing(9)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.verticalLayout_7.setContentsMargins(9, 9, 9, 9)
        self.verticalLayoutWidget_4 = QWidget(self.widget)
        self.verticalLayoutWidget_4.setObjectName(u"verticalLayoutWidget_4")
        self.verticalLayoutWidget_4.setGeometry(QRect(10, 310, 811, 431))
        self.layoutChart = QVBoxLayout(self.verticalLayoutWidget_4)
        self.layoutChart.setSpacing(2)
        self.layoutChart.setObjectName(u"layoutChart")
        self.layoutChart.setContentsMargins(2, 2, 2, 2)
        self.resultaatChart = PlotWidget(self.widget)
        self.resultaatChart.setObjectName(u"resultaatChart")
        self.resultaatChart.setGeometry(QRect(10, 960, 811, 191))
        self.verticalLayout_9 = QVBoxLayout(self.resultaatChart)
        self.verticalLayout_9.setSpacing(9)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.verticalLayout_9.setContentsMargins(9, 9, 9, 9)
        self.horizontalLayoutWidget = QWidget(self.widget)
        self.horizontalLayoutWidget.setObjectName(u"horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(10, 0, 801, 31))
        self.horizontalLayout = QHBoxLayout(self.horizontalLayoutWidget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.asset_selector = QComboBox(self.horizontalLayoutWidget)
        self.asset_selector.setObjectName(u"asset_selector")
        self.asset_selector.setMaximumSize(QSize(150, 16777215))
        self.asset_selector.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout.addWidget(self.asset_selector, 0, Qt.AlignmentFlag.AlignLeft)

        self.stepSizeBox = QDoubleSpinBox(self.horizontalLayoutWidget)
        self.stepSizeBox.setObjectName(u"stepSizeBox")
        self.stepSizeBox.setMaximumSize(QSize(80, 16777215))
        self.stepSizeBox.setStyleSheet(u"background-color: rgb(230, 230, 230);")
        self.stepSizeBox.setDecimals(6)
        self.stepSizeBox.setValue(0.020000000000000)

        self.horizontalLayout.addWidget(self.stepSizeBox, 0, Qt.AlignmentFlag.AlignLeft)

        self.startDate = QDateEdit(self.horizontalLayoutWidget)
        self.startDate.setObjectName(u"startDate")
        self.startDate.setMaximumSize(QSize(120, 16777215))
        self.startDate.setStyleSheet(u"background-color: rgb(230, 230, 230);")
        self.startDate.setCalendarPopup(True)

        self.horizontalLayout.addWidget(self.startDate, 0, Qt.AlignmentFlag.AlignLeft)

        self.endDate = QDateEdit(self.horizontalLayoutWidget)
        self.endDate.setObjectName(u"endDate")
        self.endDate.setMaximumSize(QSize(120, 16777215))
        self.endDate.setStyleSheet(u"background-color: rgb(230, 230, 230);")
        self.endDate.setCalendarPopup(True)

        self.horizontalLayout.addWidget(self.endDate, 0, Qt.AlignmentFlag.AlignLeft)

        self.comboBoxStatus = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxStatus.setObjectName(u"comboBoxStatus")
        self.comboBoxStatus.setMaximumSize(QSize(80, 16777215))
        self.comboBoxStatus.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout.addWidget(self.comboBoxStatus)

        self.comboBoxValueGrow = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxValueGrow.setObjectName(u"comboBoxValueGrow")
        self.comboBoxValueGrow.setMaximumSize(QSize(80, 16777215))
        self.comboBoxValueGrow.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout.addWidget(self.comboBoxValueGrow)

        self.comboBoxSector = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxSector.setObjectName(u"comboBoxSector")
        self.comboBoxSector.setMaximumSize(QSize(140, 16777215))
        self.comboBoxSector.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout.addWidget(self.comboBoxSector)

        self.comboBoxRegio = QComboBox(self.horizontalLayoutWidget)
        self.comboBoxRegio.setObjectName(u"comboBoxRegio")
        self.comboBoxRegio.setMaximumSize(QSize(60, 16777215))
        self.comboBoxRegio.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout.addWidget(self.comboBoxRegio)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.horizontalLayoutWidget_2 = QWidget(self.widget)
        self.horizontalLayoutWidget_2.setObjectName(u"horizontalLayoutWidget_2")
        self.horizontalLayoutWidget_2.setGeometry(QRect(830, 0, 711, 31))
        self.horizontalLayout_2 = QHBoxLayout(self.horizontalLayoutWidget_2)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)

        self.lineEditFilterOptiesOpen = QLineEdit(self.horizontalLayoutWidget_2)
        self.lineEditFilterOptiesOpen.setObjectName(u"lineEditFilterOptiesOpen")
        self.lineEditFilterOptiesOpen.setMinimumSize(QSize(300, 24))
        self.lineEditFilterOptiesOpen.setMaximumSize(QSize(450, 16777215))
        self.lineEditFilterOptiesOpen.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout_2.addWidget(self.lineEditFilterOptiesOpen, 0, Qt.AlignmentFlag.AlignRight)

        self.buttonClearFiltersOptiesOpen = QPushButton(self.horizontalLayoutWidget_2)
        self.buttonClearFiltersOptiesOpen.setObjectName(u"buttonClearFiltersOptiesOpen")
        self.buttonClearFiltersOptiesOpen.setMaximumSize(QSize(150, 16777215))
        self.buttonClearFiltersOptiesOpen.setStyleSheet(u"background-color: rgb(230, 230, 230);")

        self.horizontalLayout_2.addWidget(self.buttonClearFiltersOptiesOpen, 0, Qt.AlignmentFlag.AlignRight)

        self.payoff_table = QTableWidget(self.widget)
        self.payoff_table.setObjectName(u"payoff_table")
        self.payoff_table.setGeometry(QRect(6, 40, 811, 257))
        self.payoff_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.payoff_table.verticalHeader().setMinimumSectionSize(30)
        self.tableViewOptiesOpen = QTableView(self.widget)
        self.tableViewOptiesOpen.setObjectName(u"tableViewOptiesOpen")
        self.tableViewOptiesOpen.setGeometry(QRect(830, 40, 1081, 257))
        self.tableViewOptiesOpen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.testOrdersTable = QTableWidget(self.widget)
        self.testOrdersTable.setObjectName(u"testOrdersTable")
        self.testOrdersTable.setGeometry(QRect(830, 610, 711, 291))
        self.buttonAddTestOrder = QPushButton(self.widget)
        self.buttonAddTestOrder.setObjectName(u"buttonAddTestOrder")
        self.buttonAddTestOrder.setGeometry(QRect(1130, 570, 121, 31))
        self.buttonDeleteTestOrder = QPushButton(self.widget)
        self.buttonDeleteTestOrder.setObjectName(u"buttonDeleteTestOrder")
        self.buttonDeleteTestOrder.setGeometry(QRect(1260, 570, 121, 31))
        self.checkBoxAssetOrdersOnly = QCheckBox(self.widget)
        self.checkBoxAssetOrdersOnly.setObjectName(u"checkBoxAssetOrdersOnly")
        self.checkBoxAssetOrdersOnly.setGeometry(QRect(972, 576, 151, 20))
        self.checkBoxEnableTestOrders = QCheckBox(self.widget)
        self.checkBoxEnableTestOrders.setObjectName(u"checkBoxEnableTestOrders")
        self.checkBoxEnableTestOrders.setGeometry(QRect(832, 576, 121, 20))
        self.tableViewOptiesOpenPut = QTableView(self.widget)
        self.tableViewOptiesOpenPut.setObjectName(u"tableViewOptiesOpenPut")
        self.tableViewOptiesOpenPut.setGeometry(QRect(830, 440, 1081, 117))
        self.tableViewOptiesOpenPut.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tableViewOptiesOpenCall = QTableView(self.widget)
        self.tableViewOptiesOpenCall.setObjectName(u"tableViewOptiesOpenCall")
        self.tableViewOptiesOpenCall.setGeometry(QRect(830, 310, 1081, 117))
        self.tableViewOptiesOpenCall.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tableViewAandelen = QTableView(self.widget)
        self.tableViewAandelen.setObjectName(u"tableViewAandelen")
        self.tableViewAandelen.setGeometry(QRect(830, 921, 707, 77))
        self.tableViewAandelen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tableViewSprinters = QTableView(self.widget)
        self.tableViewSprinters.setObjectName(u"tableViewSprinters")
        self.tableViewSprinters.setGeometry(QRect(830, 1000, 707, 78))
        self.tableViewSprinters.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.verticalLayout_2.addWidget(self.widget)

        QWidget.setTabOrder(self.asset_selector, self.stepSizeBox)
        QWidget.setTabOrder(self.stepSizeBox, self.startDate)
        QWidget.setTabOrder(self.startDate, self.endDate)
        QWidget.setTabOrder(self.endDate, self.comboBoxStatus)
        QWidget.setTabOrder(self.comboBoxStatus, self.comboBoxValueGrow)
        QWidget.setTabOrder(self.comboBoxValueGrow, self.comboBoxSector)
        QWidget.setTabOrder(self.comboBoxSector, self.comboBoxRegio)
        QWidget.setTabOrder(self.comboBoxRegio, self.lineEditFilterOptiesOpen)
        QWidget.setTabOrder(self.lineEditFilterOptiesOpen, self.buttonClearFiltersOptiesOpen)
        QWidget.setTabOrder(self.buttonClearFiltersOptiesOpen, self.payoff_table)
        QWidget.setTabOrder(self.payoff_table, self.tableViewOptiesOpen)

        self.retranslateUi(SingleAssetAnalyseTab)

        QMetaObject.connectSlotsByName(SingleAssetAnalyseTab)
    # setupUi

    def retranslateUi(self, SingleAssetAnalyseTab):
        SingleAssetAnalyseTab.setWindowTitle(QCoreApplication.translate("SingleAssetAnalyseTab", u"Form", None))
        self.buttonClearFiltersOptiesOpen.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Clear Filter", None))
        self.buttonAddTestOrder.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Add test order", None))
        self.buttonDeleteTestOrder.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Delete test order", None))
        self.checkBoxAssetOrdersOnly.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Show asset orders only", None))
        self.checkBoxEnableTestOrders.setText(QCoreApplication.translate("SingleAssetAnalyseTab", u"Enable Test Orders", None))
    # retranslateUi

