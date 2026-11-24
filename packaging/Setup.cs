using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;
[assembly: AssemblyProduct("RecoverX Recovery Studio")]
[assembly: AssemblyTitle("RecoverX Desktop Setup")]
[assembly: AssemblyFileVersion("1.0.0.0")]
public static class Setup{
    static string Extract(Stream payload,string folder){
        Directory.CreateDirectory(folder);
        if(Directory.GetFileSystemEntries(folder).Length!=0)throw new IOException("Choose an empty installation folder.");
        string root=Path.GetFullPath(folder).TrimEnd('\\')+"\\";
        using(var archive=new ZipArchive(payload,ZipArchiveMode.Read,true)){
            foreach(var entry in archive.Entries){
                if(!entry.FullName.StartsWith("RecoverX/",StringComparison.Ordinal)||entry.FullName.EndsWith("/"))continue;
                string name=entry.FullName.Substring(9);
                string path=Path.GetFullPath(Path.Combine(root,name));
                if(!path.StartsWith(root,StringComparison.OrdinalIgnoreCase))throw new IOException("An archive entry has an invalid path.");
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                using(var input=entry.Open())using(var output=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None)){
                    input.CopyTo(output);if(output.Length!=entry.Length)throw new IOException("An installation file was incomplete.");
                }
            }
        }
        string exe=Path.Combine(root,"RecoverX.exe");if(!File.Exists(exe))throw new IOException("The application executable is missing.");return exe;
    }
    static void MakeShortcut(string link,string exe){
        dynamic shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic shortcut=shell.CreateShortcut(link);
        shortcut.TargetPath=exe;shortcut.WorkingDirectory=Path.GetDirectoryName(exe);shortcut.IconLocation=exe+",0";shortcut.Description="RecoverX Recovery Studio";shortcut.Save();
        dynamic saved=shell.CreateShortcut(link);if(!String.Equals((string)saved.TargetPath,exe,StringComparison.OrdinalIgnoreCase))throw new IOException("The shortcut target could not be verified.");
    }
    [STAThread]public static int Main(string[] args){
        bool test=args.Length==2 && args[0]=="--test-install";
        string stage=null;
        try{
            if(!test && args.Length!=0)return 2;
            if(!test && MessageBox.Show("Install RecoverX Recovery Studio for this Windows account, add a desktop shortcut and open the app?","RecoverX 1.0 RC1",MessageBoxButtons.OKCancel,MessageBoxIcon.Question)!=DialogResult.OK)return 0;
            string parent=test?Path.GetFullPath(args[1]):Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"RecoverX Studio");
            if(test&&!Directory.Exists(parent))Directory.CreateDirectory(parent);
            string name="1.0-rc1-"+Guid.NewGuid().ToString("N").Substring(0,8);
            stage=Path.Combine(parent,name+".partial");string final=Path.Combine(parent,name);
            using(var data=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))Extract(data,stage);
            Directory.Move(stage,final);string exe=Path.Combine(final,"RecoverX.exe");
            string linkFolder=test?parent:Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string link=Path.Combine(linkFolder,"RecoverX Recovery Studio.lnk");
            MakeShortcut(link,exe);
            if(test)File.WriteAllText(Path.Combine(parent,"setup-check.txt"),"Extracted release and verified shortcut target.\r\n"+exe);
            else Process.Start(new ProcessStartInfo(exe){WorkingDirectory=final,UseShellExecute=true});
            return 0;
        }catch(Exception ex){
            if(test)Console.Error.WriteLine(ex);
            else MessageBox.Show(ex.Message+(stage==null?"":"\n\nInstallation folder\n"+stage),"RecoverX setup",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
