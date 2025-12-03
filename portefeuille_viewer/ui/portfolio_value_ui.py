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
        self.comboBox = QComboBox(self.widget)
        self.comboBox.setObjectName(u"comboBox")

        self.horizontalLayout.addWidget(self.comboBox)

        self.comboBox_2 = QComboBox(self.widget)
        self.comboBox_2.setObjectName(u"comboBox_2")

        self.horizontalLayout.addWidget(self.comboBox_2)

        self.comboBox_3 = QComboBox(self.widget)
        self.comboBox_3.setObjectName(u"comboBox_3")

        self.horizontalLayout.addWidget(self.comboBox_3)

        self.comboBox_4 = QComboBox(self.widget)
        self.comboBox_4.setObjectName(u"comboBox_4")

        self.horizontalLayout.addWidget(self.comboBox_4)

        self.pushButton_2 = QPushButton(self.widget)
        self.pushButton_2.setObjectName(u"pushButton_2")

        self.horizontalLayout.addWidget(self.pushButton_2)


        self.horizontalLayout_2.addLayout(self.horizontalLayout)


        self.verticalLayout.addWidget(self.widget)

        self.tableView = QTableView(Form)
        self.tableView.setObjectName(u"tableView")
        self.tableView.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.verticalLayout.addWidget(self.tableView)

        QWidget.setTabOrder(self.comboBox, self.comboBox_2)
        QWidget.setTabOrder(self.comboBox_2, self.comboBox_3)
        QWidget.setTabOrder(self.comboBox_3, self.comboBox_4)
        QWidget.setTabOrder(self.comboBox_4, self.pushButton_2)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.pushButton_2.setText(QCoreApplication.translate("Form", u"PushButton", None))
    # retranslateUi

