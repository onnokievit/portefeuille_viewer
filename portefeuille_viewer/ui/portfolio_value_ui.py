# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'portfolio_value_tab.ui'
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
    QPushButton, QSizePolicy, QTableView, QVBoxLayout,
    QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1058, 879)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.widget = QWidget(Form)
        self.widget.setObjectName(u"widget")
        self.widget.setMinimumSize(QSize(0, 50))
        self.horizontalLayout_2 = QHBoxLayout(self.widget)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.comboBoxSector = QComboBox(self.widget)
        self.comboBoxSector.setObjectName(u"comboBoxSector")

        self.horizontalLayout.addWidget(self.comboBoxSector)

        self.comboBoxValueGrow = QComboBox(self.widget)
        self.comboBoxValueGrow.setObjectName(u"comboBoxValueGrow")

        self.horizontalLayout.addWidget(self.comboBoxValueGrow)

        self.comboBoxRegion = QComboBox(self.widget)
        self.comboBoxRegion.setObjectName(u"comboBoxRegion")

        self.horizontalLayout.addWidget(self.comboBoxRegion)

        self.comboBox_4 = QComboBox(self.widget)
        self.comboBox_4.setObjectName(u"comboBox_4")

        self.horizontalLayout.addWidget(self.comboBox_4)

        self.btnClearFilter = QPushButton(self.widget)
        self.btnClearFilter.setObjectName(u"btnClearFilter")

        self.horizontalLayout.addWidget(self.btnClearFilter)


        self.horizontalLayout_2.addLayout(self.horizontalLayout)


        self.verticalLayout.addWidget(self.widget)

        self.tableView = QTableView(Form)
        self.tableView.setObjectName(u"tableView")
        self.tableView.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.verticalLayout.addWidget(self.tableView)

        QWidget.setTabOrder(self.comboBoxSector, self.comboBoxValueGrow)
        QWidget.setTabOrder(self.comboBoxValueGrow, self.comboBoxRegion)
        QWidget.setTabOrder(self.comboBoxRegion, self.comboBox_4)
        QWidget.setTabOrder(self.comboBox_4, self.btnClearFilter)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.btnClearFilter.setText(QCoreApplication.translate("Form", u"PushButton", None))
    # retranslateUi

