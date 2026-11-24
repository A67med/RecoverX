using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace RecoverX {
public class Asset{
    public string name{get;set;} public string path{get;set;} public long size{get;set;}
    public string sha256{get;set;} public string engine{get;set;} public string integrity{get;set;}
    public string reference{get;set;} public string detected_type{get;set;} public bool Selected{get;set;}
    public string Group{get{
        string ext=Path.GetExtension(name).ToLowerInvariant();
        if(new[]{".jpg",".jpeg",".png",".gif",".bmp",".tif",".tiff",".webp",".heic"}.Contains(ext))return "Images";
        if(new[]{".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".odt",".txt",".rtf"}.Contains(ext))return "Documents";
        if(new[]{".mp4",".mov",".avi",".mkv",".webm",".mpeg",".mpg"}.Contains(ext))return "Video";
        if(new[]{".wav",".mp3",".ogg",".flac",".m4a"}.Contains(ext))return "Audio";
        return "Other";
    }}
}
public class Metrics{public bool ground_truth{get;set;}public int exact_recovered{get;set;}public int unrecovered{get;set;}public int outputs{get;set;}}
public class Report{public string method{get;set;}public string status{get;set;}public List<Asset> files{get;set;}public List<string> warnings{get;set;}
    public double seconds{get;set;}public Metrics metrics{get;set;}public string image_sha256{get;set;}}
public class Tick{public string stage{get;set;}public long done{get;set;}public long total{get;set;}}
public class ExportReceipt{public string destination{get;set;}public List<string> verified=new List<string>(); public List<string> failed=new List<string>();}
public static class Session{
    public static readonly string Root=AppDomain.CurrentDomain.BaseDirectory;
    public static Report Scan(string folder,string method,int sector,object known,CancellationToken cancel,Action<string,long,long> notify){
        var options=new ProcessStartInfo(Path.Combine(Root,@"runtime\python.exe"),"-B -u \""+Path.Combine(Root,@"desktop\scan.py")+"\""){
            WorkingDirectory=folder,UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,
            StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
        using(var proc=Process.Start(options)){
            var errors=proc.StandardError.ReadToEndAsync();
            var message=Encoding.UTF8.GetBytes(Json.Write(new{ @case=folder, method=method,sector=sector,known=known})+"\n");
            proc.StandardInput.BaseStream.Write(message,0,message.Length);
            proc.StandardInput.Flush();
            using(cancel.Register(()=>{try{proc.StandardInput.Close();}catch(IOException){}catch(ObjectDisposedException){}})){
                string line;
                while((line=proc.StandardOutput.ReadLine())!=null){
                    var tick=Json.Read<Tick>(line);
                    notify(tick.stage,tick.done,tick.total);
                }
                proc.WaitForExit();
            }
            string report=Path.Combine(folder,"report.json");
            string details=errors.GetAwaiter().GetResult();
            if(details.Length>0)File.WriteAllText(Path.Combine(folder,"worker.log"),details);
            if(!File.Exists(report))throw new IOException("The scan worker stopped before writing its report. Open the case folder for the worker log.");
            return Json.Read<Report>(File.ReadAllText(report));
        }
    }
    public static string AssetPath(string folder,Asset file){
        string root=Path.GetFullPath(folder).TrimEnd('\\')+"\\";
        string path=Path.GetFullPath(Path.Combine(root,file.path));
        if(!path.StartsWith(root,StringComparison.OrdinalIgnoreCase))throw new IOException("Invalid recovered file path.");
        Storage.LocalFolder(Path.GetDirectoryName(path));
        if((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new IOException("Linked files cannot be exported.");
        return path;
    }
    public static ExportReceipt Export(string folder,UsbDisk disk,List<Asset> files,CancellationToken cancel,Action<string,long,long> notify){
        Storage.LocalFolder(folder);
        if(disk!=null){
            try{Storage.ValidateOutput(disk,folder);}
            catch(IOException){Broker.Call(new Request{op="validate",sourceNumber=disk.Number,directory=folder},cancel,(header,stream)=>true);}
        }
        if(new DriveInfo(Path.GetPathRoot(folder)).AvailableFreeSpace<files.Sum(f=>f.size)+1048576)throw new IOException("Insufficient free space to export the selection.");
        string dir=Path.Combine(folder,"Recovered-"+Guid.NewGuid().ToString("N").Substring(0,8));
        Directory.CreateDirectory(dir);var result=new ExportReceipt{destination=dir};
        try{
            foreach(var f in files){
                cancel.ThrowIfCancellationRequested();
                string leaf=String.Concat(Path.GetFileName(f.name).Select(c=>Path.GetInvalidFileNameChars().Contains(c)?'_':c)).TrimEnd(' ','.');
                if(leaf.Length>110)leaf=leaf.Substring(0,95)+Path.GetExtension(leaf).Substring(0,Math.Min(12,Path.GetExtension(leaf).Length));
                // Numeric prefix avoids DOS device aliases and same-name collisions.
                string dest=Path.Combine(dir,(result.failed.Count+result.verified.Count+1).ToString("D4")+"-"+leaf);
                string temp=dest+".partial";
                try{
                    using(var input=File.OpenRead(AssetPath(folder,f)))
                    using(var output=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.None)){
                        if(input.Length!=f.size)throw new IOException("File size changed.");
                        if(f.size>0)Acquisition.CopyExact(input,output,f.size,cancel,(a,b)=>{});
                        output.Flush(true);
                    }
                    using(var read=File.OpenRead(temp))using(var sha=SHA256.Create()){
                        var actual=BitConverter.ToString(sha.ComputeHash(read)).Replace("-","");
                        if(!actual.Equals(f.sha256,StringComparison.OrdinalIgnoreCase))throw new IOException("Export hash mismatch.");
                    }
                    File.Move(temp,dest);result.verified.Add(Path.GetFileName(dest)+"  "+f.sha256);
                }catch(IOException ex){result.failed.Add(f.name+" · "+ex.Message);}
                notify("Verifying exported copies",result.verified.Count+result.failed.Count,files.Count);
            }
        }finally{Json.Save(Path.Combine(dir,"export-receipt.json"),result);}
        return result;
    }
}
}
