# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'repository_tester1.ui'
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
    QPushButton, QSizePolicy, QSpacerItem, QTableView,
    QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(1537, 975)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.widget = QWidget(Form)
        self.widget.setObjectName(u"widget")
        self.widget.setMinimumSize(QSize(0, 25))
        self.widget.setMaximumSize(QSize(16777215, 30))
        self.horizontalLayout_2 = QHBoxLayout(self.widget)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.comboBox = QComboBox(self.widget)
        self.comboBox.setObjectName(u"comboBox")
        self.comboBox.setMinimumSize(QSize(350, 25))
        self.comboBox.setMaximumSize(QSize(350, 16777215))

        self.horizontalLayout_2.addWidget(self.comboBox)

        self.btnExportExcel = QPushButton(self.widget)
        self.btnExportExcel.setObjectName(u"btnExportExcel")
        self.btnExportExcel.setMinimumSize(QSize(0, 25))

        self.horizontalLayout_2.addWidget(self.btnExportExcel)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)


        self.verticalLayout.addWidget(self.widget)

        self.widget_2 = QWidget(Form)
        self.widget_2.setObjectName(u"widget_2")
        self.horizontalLayout = QHBoxLayout(self.widget_2)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.tableView = QTableView(self.widget_2)
        self.tableView.setObjectName(u"tableView")
        font = QFont()
        font.setPointSize(8)
        self.tableView.setFont(font)
        self.tableView.setSortingEnabled(True)

        self.horizontalLayout.addWidget(self.tableView)


        self.verticalLayout.addWidget(self.widget_2)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.btnExportExcel.setText(QCoreApplication.translate("Form", u"To Excel", None))
    # retranslateUi

