# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'sector_tab.ui'
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
from PySide6.QtWidgets import (QApplication, QFrame, QHeaderView, QSizePolicy,
    QTableView, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(2500, 2000)
        self.pieChartValueLineair = QFrame(Form)
        self.pieChartValueLineair.setObjectName(u"pieChartValueLineair")
        self.pieChartValueLineair.setGeometry(QRect(690, 10, 561, 481))
        self.pieChartValueLineair.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueLineair.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueLineairNaOpties = QFrame(Form)
        self.pieChartValueLineairNaOpties.setObjectName(u"pieChartValueLineairNaOpties")
        self.pieChartValueLineairNaOpties.setGeometry(QRect(1850, 10, 561, 481))
        self.pieChartValueLineairNaOpties.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueLineairNaOpties.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueLineairPutITM = QFrame(Form)
        self.pieChartValueLineairPutITM.setObjectName(u"pieChartValueLineairPutITM")
        self.pieChartValueLineairPutITM.setGeometry(QRect(1270, 10, 561, 481))
        self.pieChartValueLineairPutITM.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueLineairPutITM.setFrameShadow(QFrame.Shadow.Raised)
        self.tableSectorValuesLineair = QTableView(Form)
        self.tableSectorValuesLineair.setObjectName(u"tableSectorValuesLineair")
        self.tableSectorValuesLineair.setGeometry(QRect(10, 10, 661, 481))
        self.pieChartValueDeltaPutITM = QFrame(Form)
        self.pieChartValueDeltaPutITM.setObjectName(u"pieChartValueDeltaPutITM")
        self.pieChartValueDeltaPutITM.setGeometry(QRect(1280, 600, 561, 481))
        self.pieChartValueDeltaPutITM.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueDeltaPutITM.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueDelta = QFrame(Form)
        self.pieChartValueDelta.setObjectName(u"pieChartValueDelta")
        self.pieChartValueDelta.setGeometry(QRect(700, 600, 561, 481))
        self.pieChartValueDelta.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueDelta.setFrameShadow(QFrame.Shadow.Raised)
        self.tableSectorValuesDelta = QTableView(Form)
        self.tableSectorValuesDelta.setObjectName(u"tableSectorValuesDelta")
        self.tableSectorValuesDelta.setGeometry(QRect(20, 600, 661, 481))

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
    # retranslateUi

