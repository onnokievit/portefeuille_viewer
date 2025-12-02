# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'orders_tab_1.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QSpacerItem,
    QTableView, QVBoxLayout, QWidget)

from .smartcombo import SmartCombo

class Ui_OrdersTabUI(object):
    def setupUi(self, OrdersTabUI):
        if not OrdersTabUI.objectName():
            OrdersTabUI.setObjectName(u"OrdersTabUI")
        OrdersTabUI.resize(1387, 978)
        self.verticalLayout = QVBoxLayout(OrdersTabUI)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.groupBoxOrders = QGroupBox(OrdersTabUI)
        self.groupBoxOrders.setObjectName(u"groupBoxOrders")
        self.gridLayoutOrders = QGridLayout(self.groupBoxOrders)
        self.gridLayoutOrders.setObjectName(u"gridLayoutOrders")
        self.labelOptieExp = QLabel(self.groupBoxOrders)
        self.labelOptieExp.setObjectName(u"labelOptieExp")

        self.gridLayoutOrders.addWidget(self.labelOptieExp, 0, 11, 1, 1)

        self.labelAssetType = QLabel(self.groupBoxOrders)
        self.labelAssetType.setObjectName(u"labelAssetType")

        self.gridLayoutOrders.addWidget(self.labelAssetType, 0, 5, 1, 1)

        self.labelBroker = QLabel(self.groupBoxOrders)
        self.labelBroker.setObjectName(u"labelBroker")

        self.gridLayoutOrders.addWidget(self.labelBroker, 0, 3, 1, 1)

        self.comboTransType1 = SmartCombo(self.groupBoxOrders)
        self.comboTransType1.setObjectName(u"comboTransType1")

        self.gridLayoutOrders.addWidget(self.comboTransType1, 1, 7, 1, 1)

        self.lineEditFee2 = QLineEdit(self.groupBoxOrders)
        self.lineEditFee2.setObjectName(u"lineEditFee2")

        self.gridLayoutOrders.addWidget(self.lineEditFee2, 2, 10, 1, 1)

        self.comboBroker1 = SmartCombo(self.groupBoxOrders)
        self.comboBroker1.setObjectName(u"comboBroker1")

        self.gridLayoutOrders.addWidget(self.comboBroker1, 1, 3, 1, 1)

        self.lineEditPrijs1 = QLineEdit(self.groupBoxOrders)
        self.lineEditPrijs1.setObjectName(u"lineEditPrijs1")

        self.gridLayoutOrders.addWidget(self.lineEditPrijs1, 1, 9, 1, 1)

        self.lineEditOptieStrike1 = QLineEdit(self.groupBoxOrders)
        self.lineEditOptieStrike1.setObjectName(u"lineEditOptieStrike1")

        self.gridLayoutOrders.addWidget(self.lineEditOptieStrike1, 1, 12, 1, 1)

        self.lineEditOptieExp2 = QLineEdit(self.groupBoxOrders)
        self.lineEditOptieExp2.setObjectName(u"lineEditOptieExp2")

        self.gridLayoutOrders.addWidget(self.lineEditOptieExp2, 2, 11, 1, 1)

        self.comboAssetType2 = SmartCombo(self.groupBoxOrders)
        self.comboAssetType2.setObjectName(u"comboAssetType2")

        self.gridLayoutOrders.addWidget(self.comboAssetType2, 2, 5, 1, 1)

        self.comboAssetRollup2 = SmartCombo(self.groupBoxOrders)
        self.comboAssetRollup2.setObjectName(u"comboAssetRollup2")

        self.gridLayoutOrders.addWidget(self.comboAssetRollup2, 2, 4, 1, 1)

        self.labelFee = QLabel(self.groupBoxOrders)
        self.labelFee.setObjectName(u"labelFee")

        self.gridLayoutOrders.addWidget(self.labelFee, 0, 10, 1, 1)

        self.comboDetail2 = SmartCombo(self.groupBoxOrders)
        self.comboDetail2.setObjectName(u"comboDetail2")

        self.gridLayoutOrders.addWidget(self.comboDetail2, 2, 6, 1, 1)

        self.lineEditAantal2 = QLineEdit(self.groupBoxOrders)
        self.lineEditAantal2.setObjectName(u"lineEditAantal2")

        self.gridLayoutOrders.addWidget(self.lineEditAantal2, 2, 8, 1, 1)

        self.labelTransType = QLabel(self.groupBoxOrders)
        self.labelTransType.setObjectName(u"labelTransType")

        self.gridLayoutOrders.addWidget(self.labelTransType, 0, 7, 1, 1)

        self.lineEditOptieStrike2 = QLineEdit(self.groupBoxOrders)
        self.lineEditOptieStrike2.setObjectName(u"lineEditOptieStrike2")

        self.gridLayoutOrders.addWidget(self.lineEditOptieStrike2, 2, 12, 1, 1)

        self.comboBroker2 = SmartCombo(self.groupBoxOrders)
        self.comboBroker2.setObjectName(u"comboBroker2")

        self.gridLayoutOrders.addWidget(self.comboBroker2, 2, 3, 1, 1)

        self.labelOorsprong2 = QLabel(self.groupBoxOrders)
        self.labelOorsprong2.setObjectName(u"labelOorsprong2")

        self.gridLayoutOrders.addWidget(self.labelOorsprong2, 2, 1, 1, 1)

        self.labelOorsprong = QLabel(self.groupBoxOrders)
        self.labelOorsprong.setObjectName(u"labelOorsprong")

        self.gridLayoutOrders.addWidget(self.labelOorsprong, 0, 1, 1, 1)

        self.lineEditOptieExp1 = QLineEdit(self.groupBoxOrders)
        self.lineEditOptieExp1.setObjectName(u"lineEditOptieExp1")

        self.gridLayoutOrders.addWidget(self.lineEditOptieExp1, 1, 11, 1, 1)

        self.lineEditFee1 = QLineEdit(self.groupBoxOrders)
        self.lineEditFee1.setObjectName(u"lineEditFee1")

        self.gridLayoutOrders.addWidget(self.lineEditFee1, 1, 10, 1, 1)

        self.labelAantal = QLabel(self.groupBoxOrders)
        self.labelAantal.setObjectName(u"labelAantal")

        self.gridLayoutOrders.addWidget(self.labelAantal, 0, 8, 1, 1)

        self.comboOorsprong1 = SmartCombo(self.groupBoxOrders)
        self.comboOorsprong1.setObjectName(u"comboOorsprong1")

        self.gridLayoutOrders.addWidget(self.comboOorsprong1, 1, 1, 1, 1)

        self.lineEditPrijs2 = QLineEdit(self.groupBoxOrders)
        self.lineEditPrijs2.setObjectName(u"lineEditPrijs2")

        self.gridLayoutOrders.addWidget(self.lineEditPrijs2, 2, 9, 1, 1)

        self.labelPrijs = QLabel(self.groupBoxOrders)
        self.labelPrijs.setObjectName(u"labelPrijs")

        self.gridLayoutOrders.addWidget(self.labelPrijs, 0, 9, 1, 1)

        self.labelOptieCP = QLabel(self.groupBoxOrders)
        self.labelOptieCP.setObjectName(u"labelOptieCP")

        self.gridLayoutOrders.addWidget(self.labelOptieCP, 0, 13, 1, 1)

        self.labelDetail = QLabel(self.groupBoxOrders)
        self.labelDetail.setObjectName(u"labelDetail")

        self.gridLayoutOrders.addWidget(self.labelDetail, 0, 6, 1, 1)

        self.comboAssetRollup1 = SmartCombo(self.groupBoxOrders)
        self.comboAssetRollup1.setObjectName(u"comboAssetRollup1")

        self.gridLayoutOrders.addWidget(self.comboAssetRollup1, 1, 4, 1, 1)

        self.comboAssetType1 = SmartCombo(self.groupBoxOrders)
        self.comboAssetType1.setObjectName(u"comboAssetType1")

        self.gridLayoutOrders.addWidget(self.comboAssetType1, 1, 5, 1, 1)

        self.lineEditAantal1 = QLineEdit(self.groupBoxOrders)
        self.lineEditAantal1.setObjectName(u"lineEditAantal1")

        self.gridLayoutOrders.addWidget(self.lineEditAantal1, 1, 8, 1, 1)

        self.comboOptieCP1 = SmartCombo(self.groupBoxOrders)
        self.comboOptieCP1.setObjectName(u"comboOptieCP1")

        self.gridLayoutOrders.addWidget(self.comboOptieCP1, 1, 13, 1, 1)

        self.comboDetail1 = SmartCombo(self.groupBoxOrders)
        self.comboDetail1.setObjectName(u"comboDetail1")

        self.gridLayoutOrders.addWidget(self.comboDetail1, 1, 6, 1, 1)

        self.comboOptieCP2 = SmartCombo(self.groupBoxOrders)
        self.comboOptieCP2.setObjectName(u"comboOptieCP2")

        self.gridLayoutOrders.addWidget(self.comboOptieCP2, 2, 13, 1, 1)

        self.comboTransType2 = SmartCombo(self.groupBoxOrders)
        self.comboTransType2.setObjectName(u"comboTransType2")

        self.gridLayoutOrders.addWidget(self.comboTransType2, 2, 7, 1, 1)

        self.labelAssetRollup = QLabel(self.groupBoxOrders)
        self.labelAssetRollup.setObjectName(u"labelAssetRollup")

        self.gridLayoutOrders.addWidget(self.labelAssetRollup, 0, 4, 1, 1)

        self.labelOptieStrike = QLabel(self.groupBoxOrders)
        self.labelOptieStrike.setObjectName(u"labelOptieStrike")

        self.gridLayoutOrders.addWidget(self.labelOptieStrike, 0, 12, 1, 1)

        self.dateEditOrder1 = QDateEdit(self.groupBoxOrders)
        self.dateEditOrder1.setObjectName(u"dateEditOrder1")

        self.gridLayoutOrders.addWidget(self.dateEditOrder1, 1, 0, 1, 1)

        self.dateEditOrder2 = QDateEdit(self.groupBoxOrders)
        self.dateEditOrder2.setObjectName(u"dateEditOrder2")

        self.gridLayoutOrders.addWidget(self.dateEditOrder2, 2, 0, 1, 1)


        self.verticalLayout.addWidget(self.groupBoxOrders)

        self.horizontalLayoutButtons = QHBoxLayout()
        self.horizontalLayoutButtons.setObjectName(u"horizontalLayoutButtons")
        self.buttonSave = QPushButton(OrdersTabUI)
        self.buttonSave.setObjectName(u"buttonSave")

        self.horizontalLayoutButtons.addWidget(self.buttonSave)

        self.buttonReset = QPushButton(OrdersTabUI)
        self.buttonReset.setObjectName(u"buttonReset")

        self.horizontalLayoutButtons.addWidget(self.buttonReset)

        self.buttonDelete = QPushButton(OrdersTabUI)
        self.buttonDelete.setObjectName(u"buttonDelete")
        self.buttonDelete.setStyleSheet(u"background-color: rgb(255, 107, 107);\n"
"color: rgb(255, 255, 255);")

        self.horizontalLayoutButtons.addWidget(self.buttonDelete)

        self.labelDatabase = QLabel(OrdersTabUI)
        self.labelDatabase.setObjectName(u"labelDatabase")

        self.horizontalLayoutButtons.addWidget(self.labelDatabase)

        self.comboDatabase = QComboBox(OrdersTabUI)
        self.comboDatabase.setObjectName(u"comboDatabase")

        self.horizontalLayoutButtons.addWidget(self.comboDatabase)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayoutButtons.addItem(self.horizontalSpacer)

        self.labelFilter = QLabel(OrdersTabUI)
        self.labelFilter.setObjectName(u"labelFilter")

        self.horizontalLayoutButtons.addWidget(self.labelFilter)

        self.lineEditFilter = QLineEdit(OrdersTabUI)
        self.lineEditFilter.setObjectName(u"lineEditFilter")

        self.horizontalLayoutButtons.addWidget(self.lineEditFilter)

        self.buttonClearFilters = QPushButton(OrdersTabUI)
        self.buttonClearFilters.setObjectName(u"buttonClearFilters")

        self.horizontalLayoutButtons.addWidget(self.buttonClearFilters)


        self.verticalLayout.addLayout(self.horizontalLayoutButtons)

        self.tableViewOrders = QTableView(OrdersTabUI)
        self.tableViewOrders.setObjectName(u"tableViewOrders")
        self.tableViewOrders.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.verticalLayout.addWidget(self.tableViewOrders)

        QWidget.setTabOrder(self.comboOorsprong1, self.comboBroker1)
        QWidget.setTabOrder(self.comboBroker1, self.comboAssetRollup1)
        QWidget.setTabOrder(self.comboAssetRollup1, self.comboAssetType1)
        QWidget.setTabOrder(self.comboAssetType1, self.comboDetail1)
        QWidget.setTabOrder(self.comboDetail1, self.comboTransType1)
        QWidget.setTabOrder(self.comboTransType1, self.lineEditAantal1)
        QWidget.setTabOrder(self.lineEditAantal1, self.lineEditPrijs1)
        QWidget.setTabOrder(self.lineEditPrijs1, self.lineEditFee1)
        QWidget.setTabOrder(self.lineEditFee1, self.lineEditOptieExp1)
        QWidget.setTabOrder(self.lineEditOptieExp1, self.lineEditOptieStrike1)
        QWidget.setTabOrder(self.lineEditOptieStrike1, self.comboOptieCP1)
        QWidget.setTabOrder(self.comboOptieCP1, self.comboBroker2)
        QWidget.setTabOrder(self.comboBroker2, self.comboAssetRollup2)
        QWidget.setTabOrder(self.comboAssetRollup2, self.comboAssetType2)
        QWidget.setTabOrder(self.comboAssetType2, self.comboDetail2)
        QWidget.setTabOrder(self.comboDetail2, self.comboTransType2)
        QWidget.setTabOrder(self.comboTransType2, self.lineEditAantal2)
        QWidget.setTabOrder(self.lineEditAantal2, self.lineEditPrijs2)
        QWidget.setTabOrder(self.lineEditPrijs2, self.lineEditFee2)
        QWidget.setTabOrder(self.lineEditFee2, self.lineEditOptieExp2)
        QWidget.setTabOrder(self.lineEditOptieExp2, self.lineEditOptieStrike2)
        QWidget.setTabOrder(self.lineEditOptieStrike2, self.comboOptieCP2)
        QWidget.setTabOrder(self.comboOptieCP2, self.buttonSave)
        QWidget.setTabOrder(self.buttonSave, self.buttonReset)
        QWidget.setTabOrder(self.buttonReset, self.buttonDelete)
        QWidget.setTabOrder(self.buttonDelete, self.comboDatabase)
        QWidget.setTabOrder(self.comboDatabase, self.lineEditFilter)
        QWidget.setTabOrder(self.lineEditFilter, self.buttonClearFilters)
        QWidget.setTabOrder(self.buttonClearFilters, self.dateEditOrder1)
        QWidget.setTabOrder(self.dateEditOrder1, self.dateEditOrder2)
        QWidget.setTabOrder(self.dateEditOrder2, self.tableViewOrders)

        self.retranslateUi(OrdersTabUI)

        QMetaObject.connectSlotsByName(OrdersTabUI)
    # setupUi

    def retranslateUi(self, OrdersTabUI):
        self.groupBoxOrders.setTitle(QCoreApplication.translate("OrdersTabUI", u"Orders", None))
        self.labelOptieExp.setText(QCoreApplication.translate("OrdersTabUI", u"Optie Exp.", None))
        self.labelAssetType.setText(QCoreApplication.translate("OrdersTabUI", u"Type", None))
        self.labelBroker.setText(QCoreApplication.translate("OrdersTabUI", u"Broker", None))
        self.labelFee.setText(QCoreApplication.translate("OrdersTabUI", u"Fee", None))
        self.labelTransType.setText(QCoreApplication.translate("OrdersTabUI", u"Koop/Verkoop", None))
        self.labelOorsprong2.setText("")
        self.labelOorsprong.setText(QCoreApplication.translate("OrdersTabUI", u"Oorsprong", None))
        self.labelAantal.setText(QCoreApplication.translate("OrdersTabUI", u"Aantal", None))
        self.labelPrijs.setText(QCoreApplication.translate("OrdersTabUI", u"Prijs", None))
        self.labelOptieCP.setText(QCoreApplication.translate("OrdersTabUI", u"Call/Put", None))
        self.labelDetail.setText(QCoreApplication.translate("OrdersTabUI", u"Asset Detail", None))
        self.labelAssetRollup.setText(QCoreApplication.translate("OrdersTabUI", u"Asset Rollup", None))
        self.labelOptieStrike.setText(QCoreApplication.translate("OrdersTabUI", u"Optie Strike", None))
        self.buttonSave.setText(QCoreApplication.translate("OrdersTabUI", u"Opslaan", None))
        self.buttonReset.setText(QCoreApplication.translate("OrdersTabUI", u"Reset", None))
        self.buttonDelete.setText(QCoreApplication.translate("OrdersTabUI", u"Verwijderen", None))
        self.labelDatabase.setText(QCoreApplication.translate("OrdersTabUI", u"Database:", None))
        self.labelFilter.setText(QCoreApplication.translate("OrdersTabUI", u"Filter:", None))
        self.buttonClearFilters.setText(QCoreApplication.translate("OrdersTabUI", u"Filters wissen", None))
        pass
    # retranslateUi

