// SPDX-License-Identifier: GPL-2.0-or-later
// Test-only editor: the output file is written exclusively by a Save UI action.
#include <QApplication>
#include <QFile>
#include <QLabel>
#include <QPushButton>
#include <QShortcut>
#include <QTextEdit>
#include <QVBoxLayout>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    if (argc != 2) return 2;
    const QString output = QString::fromLocal8Bit(argv[1]);
    QWidget window;
    window.setWindowTitle("Plasma VNC input regression");
    window.resize(560, 380);
    auto layout = new QVBoxLayout(&window);
    layout->setContentsMargins(12, 12, 12, 12);
    auto banner = new QLabel("VNC mouse drag and keyboard test");
    banner->setFixedHeight(44);
    banner->setAlignment(Qt::AlignCenter);
    banner->setStyleSheet("background: rgb(18,210,178); color: black; font-size: 18px;");
    layout->addWidget(banner);
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
