using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// The desktop window owns only the WebView. The Python launcher owns the local
// service and all project operations. No general native-script bridge is exposed.
internal sealed class StudioWindow : Form
{
    readonly WebView2 view = new WebView2();
    readonly Uri origin;
    readonly string profile;
    readonly string diagnostic;
    readonly int automationPort;
    readonly Label loading = new Label();
    bool initialized;

    StudioWindow(Uri url, string data, string report, int debuggingPort)
    {
        origin = url;
        profile = data;
        diagnostic = report;
        automationPort = debuggingPort;
        Text = "FormToPart Studio - Design, Materials and BOM";
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1440, 900);
        MinimumSize = new Size(980, 650);
        WindowState = FormWindowState.Maximized;
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(248, 249, 245);
        Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application;
        view.Dock = DockStyle.Fill;
        loading.Text = "Opening FormToPart Studio...";
        loading.Dock = DockStyle.Fill;
        loading.TextAlign = ContentAlignment.MiddleCenter;
        loading.Font = new Font("Segoe UI", 18);
        Controls.Add(view);
        Controls.Add(loading);
        Shown += async (sender, e) => await Initialize();
        FormClosed += (sender, e) => view.Dispose();
    }

    bool Local(string value)
    {
        Uri candidate;
        return Uri.TryCreate(value, UriKind.Absolute, out candidate)
            && candidate.Scheme == "http" && candidate.Host == "127.0.0.1"
            && candidate.Port == origin.Port;
    }

    void Report(string status, string detail)
    {
        if (String.IsNullOrEmpty(diagnostic)) return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(diagnostic));
            string safe = detail.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");
            File.WriteAllText(diagnostic, "{\"status\":\"" + status + "\",\"detail\":\"" + safe
                + "\",\"pid\":" + System.Diagnostics.Process.GetCurrentProcess().Id
                + ",\"desktop_window\":true,\"external_browser\":false}");
        }
        catch { /* Optional test evidence must not prevent an ordinary launch. */ }
    }

    async Task Initialize()
    {
        try
        {
            string runtime = CoreWebView2Environment.GetAvailableBrowserVersionString();
            Directory.CreateDirectory(profile);
            var options = new CoreWebView2EnvironmentOptions();
            if (automationPort != 0)
                options.AdditionalBrowserArguments = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=" + automationPort;
            var environment = await CoreWebView2Environment.CreateAsync(null, profile, options);
            await view.EnsureCoreWebView2Async(environment);
            var core = view.CoreWebView2;
            core.Settings.AreDevToolsEnabled = automationPort != 0;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = true;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            await core.AddScriptToExecuteOnDocumentCreatedAsync("window.__VWC_DESKTOP__ = true;");
            core.NavigationStarting += (sender, e) =>
            {
                if (!Local(e.Uri) && e.Uri != "about:blank" && !e.Uri.StartsWith("blob:")) e.Cancel = true;
            };
            core.NewWindowRequested += (sender, e) =>
            {
                // Studio opens result previews inside the workspace. A popup
                // request must never replace the only workspace window.
                e.Handled = true;
            };
            core.PermissionRequested += (sender, e) => e.State = CoreWebView2PermissionState.Deny;
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (sender, e) =>
            {
                string request = e.Request.Uri;
                if ((request.StartsWith("https:") || request.StartsWith("http:")) && !Local(request))
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(), 403, "Local demo only", "Content-Type: text/plain");
            };
            core.DownloadStarting += (sender, e) =>
            {
                // A modal Windows dialog must not run inside a WebView2 COM
                // callback. Keep the download pending and schedule the dialog
                // after this event returns, as required by its threading model.
                var deferral = e.GetDeferral();
                e.Handled = true;
                try
                {
                    BeginInvoke(new Action(() =>
                    {
                        try
                        {
                            if (IsDisposed || Disposing) { e.Cancel = true; return; }
                            using (var dialog = new SaveFileDialog())
                            {
                                dialog.Title = "Save exported file";
                                dialog.FileName = Path.GetFileName(e.ResultFilePath);
                                dialog.OverwritePrompt = true;
                                dialog.AddExtension = true;
                                if (dialog.ShowDialog(this) == DialogResult.OK) e.ResultFilePath = dialog.FileName;
                                else e.Cancel = true;
                            }
                        }
                        catch { e.Cancel = true; }
                        finally { deferral.Complete(); }
                    }));
                }
                catch { e.Cancel = true; deferral.Complete(); }
            };
            core.NavigationCompleted += (sender, e) =>
            {
                if (e.IsSuccess)
                {
                    initialized = true;
                    loading.Hide();
                    view.Focus();
                    Report("ready", "WebView2 " + runtime);
                }
                else Report("navigation_failed", e.WebErrorStatus.ToString());
            };
            core.ProcessFailed += (sender, e) =>
            {
                Report("renderer_failed", e.ProcessFailedKind.ToString());
                loading.Text = "The view stopped. Reopen FormToPart Studio to continue your saved project.";
                loading.Show();
            };
            core.Navigate(origin.AbsoluteUri);
        }
        catch (WebView2RuntimeNotFoundException)
        {
            Report("runtime_missing", "Microsoft Edge WebView2 Runtime is required.");
            MessageBox.Show(this, "FormToPart Studio needs Microsoft Edge WebView2 Runtime.\nInstall the Microsoft Evergreen Runtime, then reopen this EXE.\nYour projects are saved locally.", "Desktop component required", MessageBoxButtons.OK, MessageBoxIcon.Information);
            Close();
        }
        catch (Exception error)
        {
            Report("startup_failed", error.GetType().Name);
            MessageBox.Show(this, "The desktop window could not open (" + error.GetType().Name + ").\nYour saved projects are unchanged. Please reopen the application.", "FormToPart Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length < 2) return 2;
        Uri url;
        if (!Uri.TryCreate(args[0], UriKind.Absolute, out url) || url.Scheme != "http" || url.Host != "127.0.0.1" || url.Port < 1) return 2;
        string report = args.Length > 2 ? args[2] : "";
        int port = 0;
        if (args.Length > 3 && (!Int32.TryParse(args[3], out port) || port < 0 || port > 65535)) return 2;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            using (var form = new StudioWindow(url, Path.GetFullPath(args[1]), report, port))
            {
                Application.Run(form);
                return form.initialized ? 0 : 1;
            }
        }
        catch (Exception error)
        {
            if (!String.IsNullOrEmpty(report))
                try { File.WriteAllText(report, "{\"status\":\"host_failed\",\"error_type\":\"" + error.GetType().Name + "\"}"); } catch { }
            return 1;
        }
    }
}
