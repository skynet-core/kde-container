// SPDX-License-Identifier: GPL-2.0-or-later
// Test-only editor: the output file is written exclusively by a Save UI action.
#include <QApplication>
#include <QClipboard>
#include <QFile>
#include <QFileDevice>
#include <QImage>
#include <QKeySequence>
#include <QLabel>
#include <QObject>
#include <QPainter>
#include <QPixmap>
#include <QPushButton>
#include <QShortcut>
#include <QString>
#include <QTextEdit>
#include <QVBoxLayout>
#include <QWidget>
#include <functional>
#include <qnamespace.h>

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  const bool publishImage =
      argc == 3 && QString::fromLocal8Bit(argv[2]) == "--publish-image";
  const bool images =
      publishImage ||
      (argc == 3 && QString::fromLocal8Bit(argv[2]) == "--images");
  if (argc != 2 && !images)
    return 2;
  const QString output = QString::fromLocal8Bit(argv[1]);
  QWidget window;
  window.setWindowTitle(images ? "Plasma clipboard image regression"
                               : "Plasma VNC input regression");
  window.resize(560, 380);
  if (publishImage)
    window.setWindowFlag(Qt::WindowStaysOnTopHint);
  auto layout = new QVBoxLayout(&window);
  layout->setContentsMargins(12, 12, 12, 12);
  auto banner = new QLabel(images ? "Clipboard image paste test"
                                  : "VNC mouse drag and keyboard test");
  banner->setFixedHeight(44);
  banner->setAlignment(Qt::AlignCenter);
  banner->setStyleSheet(
      publishImage
          ? "background: rgb(215,120,30); color: black; font-size: 18px;"
          : "background: rgb(18,210,178); color: black; font-size: 18px;");
  layout->addWidget(banner);
  if (images) {
    QImage image(3840, 2160, QImage::Format_ARGB32);
    image.fill(Qt::transparent);
    {
      QPainter painter(&image);
      painter.fillRect(0, 0, 1920, 1080,
                       publishImage ? QColor(210, 100, 180)
                                    : QColor(220, 40, 70));
      painter.fillRect(1920, 0, 1920, 1080, QColor(20, 180, 90));
      painter.fillRect(0, 1080, 1920, 1080, QColor(40, 90, 220));
      painter.fillRect(1920, 1080, 1920, 1080, QColor(0, 0, 0, 128));
    }
    QImage pasted;
    auto preview = new QLabel("Paste an image with Ctrl+V");
    preview->setAlignment(Qt::AlignCenter);
    preview->setMinimumHeight(180);
    layout->addWidget(preview, 1);
    auto status = new QLabel("No image pasted");
    layout->addWidget(status);
    auto action = [&](const QString &label, const QKeySequence &key,
                      const std::function<void()> &callback) {
      auto button = new QPushButton(label);
      layout->addWidget(button);
      QObject::connect(button, &QPushButton::clicked, &window, callback);
      auto shortcut = new QShortcut(key, &window);
      QObject::connect(shortcut, &QShortcut::activated, &window, callback);
    };
    action("Copy 4K Qt image (Ctrl+C)", QKeySequence::Copy, [&] {
      app.clipboard()->setImage(image);
      // Keep the owner alive after the test clicks Copy and returns to KWin.
      if (publishImage)
        window.hide();
    });
    action("Paste image (Ctrl+V)", QKeySequence::Paste, [&] {
      pasted = app.clipboard()->image();
      if (!pasted.isNull())
        preview->setPixmap(QPixmap::fromImage(pasted).scaled(
            480, 220, Qt::KeepAspectRatio, Qt::FastTransformation));
      status->setText(pasted.isNull() ? "No image on clipboard"
                                      : "Image pasted");
    });
    action("Save pasted PNG to host file (Ctrl+S)", QKeySequence::Save, [&] {
      status->setText(pasted.save(output, "PNG") ? "Image saved to host file"
                                                 : "Image save failed");
    });
    window.show();
    return app.exec();
  }
  auto editor = new QTextEdit;
  editor->setAcceptRichText(false);
  editor->setStyleSheet("background: white; color: black; font-size: 18px;");
  layout->addWidget(editor);
  auto save = new QPushButton("Save to host file (Ctrl+S)");
  save->setFixedHeight(36);
  layout->addWidget(save);
  auto status = new QLabel("Unsaved");
  layout->addWidget(status);
  auto saveAction = [&] {
    QFile file(output);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
      status->setText("Save failed: " + file.errorString());
      return;
    }
    file.write(editor->toPlainText().toUtf8());
    file.close();
    status->setText("Saved to host file");
  };
  QObject::connect(save, &QPushButton::clicked, &window, saveAction);
  auto shortcut = new QShortcut(QKeySequence::Save, &window);
  QObject::connect(shortcut, &QShortcut::activated, &window, saveAction);
  window.show();
  editor->setFocus();
  return app.exec();
}
