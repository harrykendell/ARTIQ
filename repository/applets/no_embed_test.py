import numpy as np
import pyqtgraph
import pyqtgraph as pg
from artiq.applets.simple import AppletRequestRPC
from artiq.applets.simple import SimpleApplet
from PyQt5 import QtCore
from PyQt5.QtWidgets import QLabel
from pyqtgraph.Qt import QtGui

translate = QtCore.QCoreApplication.translate


class SimpleAppletNoEmbed(SimpleApplet):
    def __init__(self, main_widget_class):
        super().__init__(main_widget_class)

    def args_init(self):
        super().args_init()
        self.embed = None


class SimpleImageViewer(pyqtgraph.ImageView):
    def __init__(self, args, req: AppletRequestRPC):
        self.plot_item = pg.PlotItem()
        super().__init__(view=self.plot_item)
        self.args = args
        self.req = req
        self.signals = {}

        self.crosshair = pg.CrosshairROI(
            pos=(0, 100), resizable=False, rotatable=False, movable=False
        )
        self.addItem(self.crosshair)
        self.getView().scene().sigMouseClicked.connect(self.mouseClicked)
        self.cursor_pos_label = QLabel("0.00, 0.00", self.ui.graphicsView.viewport())
        self.cursor_pos_label.setStyleSheet("background-color: white;")

        self.cursor_pos_label.setFixedSize(100, 20)
        self.cursor_pos_label.move(0, 0)

        # self.plot_item.getViewBox().invertY(True)
        # self.getView().invertY(True)
        self.buildMenu()

    def buildMenu(self):
        super().buildMenu()
        self.auto_level_action = QtGui.QAction(
            translate("ImageView", "Auto level"), self.menu
        )
        self.auto_level_action.setCheckable(True)
        self.menu.addAction(self.auto_level_action)

        self.auto_range_action = QtGui.QAction(
            translate("ImageView", "Auto range"), self.menu
        )
        self.auto_range_action.setCheckable(True)
        self.menu.addAction(self.auto_range_action)

        self.set_dataset_action = QtGui.QAction(
            translate("ImageView", "Set dataset"), self.menu
        )

    def data_changed(self, value, metadata, persist, mods):
        try:
            img = value[self.args.img]

            size_x, size_y = [i / 15 for i in np.shape(img)]
        except KeyError:
            return
        # self.ui.graphicsView.scale(1, -1)
        self.setImage(
            img,
            autoLevels=self.auto_level_action.isChecked(),
            autoRange=self.auto_range_action.isChecked(),
        )
        self.getView().invertY(False)
        self.crosshair.setSize([size_x, size_y])

    # Update the crosshair position on mouse click
    def mouseClicked(self, evt):
        # Check if the left mouse button was clicked
        if evt.button() == QtCore.Qt.MouseButton.LeftButton:
            pos = evt.scenePos()  # Get the scene position where the click occurred
            if self.view.contains(pos):  # Check if the click is within the image view
                mouse_point = self.getView().getViewBox().mapSceneToView(pos)
                self.crosshair.setPos(mouse_point.x(), mouse_point.y())
                self.cursor_pos_label.setText(
                    f"{mouse_point.x():.2f}, {self.getImageItem().height() - mouse_point.y():.2f}"
                )


def main():
    applet = SimpleAppletNoEmbed(SimpleImageViewer)
    applet.add_dataset("img", "image data (2D numpy array)")
    applet.run()


if __name__ == "__main__":
    main()
