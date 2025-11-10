# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'optie_eind.ui'
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
from PySide6.QtWidgets import (QApplication, QDateEdit, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSizePolicy, QSpacerItem,
    QTableView, QVBoxLayout, QWidget)

class Ui_OptieEindTab(object):
    def setupUi(self, OptieEindTab):
        if not OptieEindTab.objectName():
            OptieEindTab.setObjectName(u"OptieEindTab")
        OptieEindTab.resize(1224, 800)
        self.verticalLayout_main = QVBoxLayout(OptieEindTab)
        self.verticalLayout_main.setObjectName(u"verticalLayout_main")
        self.layoutTop = QHBoxLayout()
        self.layoutTop.setObjectName(u"layoutTop")
        self.lblOptieEindDatum = QLabel(OptieEindTab)
        self.lblOptieEindDatum.setObjectName(u"lblOptieEindDatum")

        self.layoutTop.addWidget(self.lblOptieEindDatum)

        self.dateOptieEind = QDateEdit(OptieEindTab)
        self.dateOptieEind.setObjectName(u"dateOptieEind")
        self.dateOptieEind.setCalendarPopup(True)
        self.layoutTop.addWidget(self.dateOptieEind)

        self.lblTransactieDatum = QLabel(OptieEindTab)
        self.lblTransactieDatum.setObjectName(u"lblTransactieDatum")
        self.layoutTop.addWidget(self.lblTransactieDatum)

        self.dateTransactie = QDateEdit(OptieEindTab)
        self.dateTransactie.setObjectName(u"dateTransactie")
        self.dateTransactie.setCalendarPopup(True)
        self.layoutTop.addWidget(self.dateTransactie)

        self.btnSelecteerBrokers = QPushButton(OptieEindTab)
        self.btnSelecteerBrokers.setObjectName(u"btnSelecteerBrokers")

        self.layoutTop.addWidget(self.btnSelecteerBrokers)

        self.btnOptieEindOphalen = QPushButton(OptieEindTab)
        self.btnOptieEindOphalen.setObjectName(u"btnOptieEindOphalen")

        self.layoutTop.addWidget(self.btnOptieEindOphalen)

        self.btnRecordsToevoegen = QPushButton(OptieEindTab)
        self.btnRecordsToevoegen.setObjectName(u"btnRecordsToevoegen")

        self.layoutTop.addWidget(self.btnRecordsToevoegen)

        self.btnTestAccountLeegmaken = QPushButton(OptieEindTab)
        self.btnTestAccountLeegmaken.setObjectName(u"btnTestAccountLeegmaken")

        self.layoutTop.addWidget(self.btnTestAccountLeegmaken)

        self.btnMoveToProductie = QPushButton(OptieEindTab)
        self.btnMoveToProductie.setObjectName(u"btnMoveToProductie")

        self.layoutTop.addWidget(self.btnMoveToProductie)
        self.spacerTop = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.layoutTop.addItem(self.spacerTop)
        self.verticalLayout_main.addLayout(self.layoutTop)
        self.tblOptieEind = QTableView(OptieEindTab)
        self.tblOptieEind.setObjectName(u"tblOptieEind")

        self.verticalLayout_main.addWidget(self.tblOptieEind)


        self.retranslateUi(OptieEindTab)

        QMetaObject.connectSlotsByName(OptieEindTab)
    # setupUi

    def retranslateUi(self, OptieEindTab):
        self.lblOptieEindDatum.setText(QCoreApplication.translate("OptieEindTab", u"Optie Eind Datum:", None))
        self.lblTransactieDatum.setText(QCoreApplication.translate("OptieEindTab", u"Transactie Datum:", None))
        self.btnSelecteerBrokers.setText(QCoreApplication.translate("OptieEindTab", u"Selecteer brokers", None))
        self.btnOptieEindOphalen.setText(QCoreApplication.translate("OptieEindTab", u"Optie Eind ophalen", None))
        self.btnRecordsToevoegen.setText(QCoreApplication.translate("OptieEindTab", u"Records toevoegen aan transactiedatabase", None))
        self.btnTestAccountLeegmaken.setText(QCoreApplication.translate("OptieEindTab", u"Test account leegmaken", None))
        self.btnMoveToProductie.setText(QCoreApplication.translate("OptieEindTab", u"Move records to productie", None))
    # retranslateUi

