# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'sector_tab_2.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHeaderView,
    QPushButton, QSizePolicy, QSlider, QTableView,
    QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(2500, 3000)
        self.pieChartValueLineair = QFrame(Form)
        self.pieChartValueLineair.setObjectName(u"pieChartValueLineair")
        self.pieChartValueLineair.setGeometry(QRect(690, 70, 561, 481))
        self.pieChartValueLineair.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueLineair.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueLineairNaOpties = QFrame(Form)
        self.pieChartValueLineairNaOpties.setObjectName(u"pieChartValueLineairNaOpties")
        self.pieChartValueLineairNaOpties.setGeometry(QRect(1270, 70, 561, 481))
        self.pieChartValueLineairNaOpties.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueLineairNaOpties.setFrameShadow(QFrame.Shadow.Raised)
        self.tableSectorValuesLineair = QTableView(Form)
        self.tableSectorValuesLineair.setObjectName(u"tableSectorValuesLineair")
        self.tableSectorValuesLineair.setGeometry(QRect(10, 70, 501, 481))
        self.pieChartValueDeltaPutITM = QFrame(Form)
        self.pieChartValueDeltaPutITM.setObjectName(u"pieChartValueDeltaPutITM")
        self.pieChartValueDeltaPutITM.setGeometry(QRect(1270, 660, 561, 481))
        self.pieChartValueDeltaPutITM.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueDeltaPutITM.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueDelta = QFrame(Form)
        self.pieChartValueDelta.setObjectName(u"pieChartValueDelta")
        self.pieChartValueDelta.setGeometry(QRect(690, 660, 561, 481))
        self.pieChartValueDelta.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueDelta.setFrameShadow(QFrame.Shadow.Raised)
        self.tableSectorValuesDelta = QTableView(Form)
        self.tableSectorValuesDelta.setObjectName(u"tableSectorValuesDelta")
        self.tableSectorValuesDelta.setGeometry(QRect(10, 660, 501, 481))
        self.putOTMRatio = QSlider(Form)
        self.putOTMRatio.setObjectName(u"putOTMRatio")
        self.putOTMRatio.setGeometry(QRect(190, 40, 231, 16))
        self.putOTMRatio.setOrientation(Qt.Orientation.Horizontal)
        self.pieChartValueGrowLineair = QFrame(Form)
        self.pieChartValueGrowLineair.setObjectName(u"pieChartValueGrowLineair")
        self.pieChartValueGrowLineair.setGeometry(QRect(690, 1220, 561, 481))
        self.pieChartValueGrowLineair.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueGrowLineair.setFrameShadow(QFrame.Shadow.Raised)
        self.tableValueGrowValuesLineair = QTableView(Form)
        self.tableValueGrowValuesLineair.setObjectName(u"tableValueGrowValuesLineair")
        self.tableValueGrowValuesLineair.setGeometry(QRect(10, 1220, 501, 481))
        self.pieChartValueGrowDelta = QFrame(Form)
        self.pieChartValueGrowDelta.setObjectName(u"pieChartValueGrowDelta")
        self.pieChartValueGrowDelta.setGeometry(QRect(690, 1810, 561, 481))
        self.pieChartValueGrowDelta.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueGrowDelta.setFrameShadow(QFrame.Shadow.Raised)
        self.tableValueGrowValuesDelta = QTableView(Form)
        self.tableValueGrowValuesDelta.setObjectName(u"tableValueGrowValuesDelta")
        self.tableValueGrowValuesDelta.setGeometry(QRect(10, 1810, 501, 481))
        self.putOTMRatioValueGrow = QSlider(Form)
        self.putOTMRatioValueGrow.setObjectName(u"putOTMRatioValueGrow")
        self.putOTMRatioValueGrow.setGeometry(QRect(190, 1190, 231, 16))
        self.putOTMRatioValueGrow.setOrientation(Qt.Orientation.Horizontal)
        self.pieChartValueGrowLineairNaOpties = QFrame(Form)
        self.pieChartValueGrowLineairNaOpties.setObjectName(u"pieChartValueGrowLineairNaOpties")
        self.pieChartValueGrowLineairNaOpties.setGeometry(QRect(1270, 1220, 561, 481))
        self.pieChartValueGrowLineairNaOpties.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueGrowLineairNaOpties.setFrameShadow(QFrame.Shadow.Raised)
        self.pieChartValueGrowDeltaPutITM = QFrame(Form)
        self.pieChartValueGrowDeltaPutITM.setObjectName(u"pieChartValueGrowDeltaPutITM")
        self.pieChartValueGrowDeltaPutITM.setGeometry(QRect(1270, 1810, 561, 481))
        self.pieChartValueGrowDeltaPutITM.setFrameShape(QFrame.Shape.StyledPanel)
        self.pieChartValueGrowDeltaPutITM.setFrameShadow(QFrame.Shadow.Raised)
        self.pushButtonOptieScenarios = QPushButton(Form)
        self.pushButtonOptieScenarios.setObjectName(u"pushButtonOptieScenarios")
        self.pushButtonOptieScenarios.setGeometry(QRect(690, 20, 141, 31))
        self.checkBoxOptieScenario = QCheckBox(Form)
        self.checkBoxOptieScenario.setObjectName(u"checkBoxOptieScenario")
        self.checkBoxOptieScenario.setGeometry(QRect(850, 27, 151, 20))

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.pushButtonOptieScenarios.setText(QCoreApplication.translate("Form", u"Optie einde scenario's", None))
        self.checkBoxOptieScenario.setText(QCoreApplication.translate("Form", u"Optie Scenario aan/uit", None))
    # retranslateUi

