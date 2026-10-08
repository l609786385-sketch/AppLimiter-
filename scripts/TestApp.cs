using System;
using System.Windows.Forms;

// A disposable, dedicated test target. Never use your real apps for native tests.
class AppLimiterTestApp {
    [STAThread]
    static void Main() {
        Application.EnableVisualStyles();
        var window = new Form();
        window.Text = "AppLimiter disposable test target";
        window.Width = 520;
        window.Height = 240;
        var text = new Label();
        text.Dock = DockStyle.Fill;
        text.Text = "AppLimiter Windows test fixture.\nThis window may be terminated by tests.\nNo user documents are opened.";
        text.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
        window.Controls.Add(text);
        Application.Run(window);
    }
}
