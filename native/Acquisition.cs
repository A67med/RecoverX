using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

namespace RecoverX {
public static class Json {
    public static string Write(object v){return new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.Serialize(v);}
    public static T Read<T>(string v){return new JavaScriptSerializer{MaxJsonLength=int.MaxValue}.Deserialize<T>(v);}
    public static void Save(string file,object v){using(var stream=new FileStream(file,FileMode.CreateNew,FileAccess.Write,FileShare.Read))
        using(var writer=new StreamWriter(stream,new UTF8Encoding(false)))writer.Write(Write(v));}
}
public class Request { public string op {get;set;} public string identity {get;set;} public string directory {get;set;} public int sourceNumber {get;set;} }
public static class Broker {
    [DllImport("kernel32")] static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe,out uint pid);
    [DllImport("kernel32")] static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe,out uint pid);
    [DllImport("kernel32",SetLastError=true)] static extern bool PeekNamedPipe(SafePipeHandle pipe,IntPtr b,int n,IntPtr got,IntPtr avail,IntPtr left);
    public static int Serve(string token,int parentId){
        Guid id;if(!Guid.TryParseExact(token,"N",out id))return 2;
        using(var pipe=new NamedPipeClientStream(".","RecoverX-"+token,PipeDirection.InOut,PipeOptions.None,TokenImpersonationLevel.Identification)){
            pipe.Connect(15000);uint pid;
            if(!GetNamedPipeServerProcessId(pipe.SafePipeHandle,out pid)||pid!=parentId)return 3;
            using(var parent=Process.GetProcessById(parentId)){
                if(!String.Equals(parent.MainModule.FileName,Process.GetCurrentProcess().MainModule.FileName,StringComparison.OrdinalIgnoreCase))return 4;
            }
            var reader=new BinaryReader(pipe);var writer=new BinaryWriter(pipe);
            bool started=false;
            try{
                var req=Json.Read<Request>(reader.ReadString());
                if(req.op=="validate"){
                    Storage.ValidateOutput(new UsbDisk{Number=req.sourceNumber},req.directory);
                    writer.Write(true);writer.Write("OK");writer.Flush();return 0;
                }
                var devices=Storage.Discover();
                if(req.op=="list"){writer.Write(true);writer.Write(Json.Write(devices));writer.Flush();return 0;}
                if(req.op!="acquire")return 5;
                var disk=devices.FirstOrDefault(d=>d.Identity==req.identity);
                if(disk==null)throw new IOException("The selected USB is no longer available. Refresh the device list.");
                using(var h=Storage.OpenSelected(disk,req.directory)){
                    writer.Write(true);writer.Write(Json.Write(disk));writer.Flush();started=true;
                    // Pipe closure cancels the narrow reader even if a storage driver is stalling.
                    using(var monitor=new Timer(o=>{if(!PeekNamedPipe(pipe.SafePipeHandle,IntPtr.Zero,0,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero))Environment.Exit(7);},null,1000,1000))
                        Storage.StreamDisk(h,disk,pipe);
                    pipe.Flush();
                }
                return 0;
            }catch(Exception ex){
                if(!started){try{writer.Write(false);writer.Write(ex.Message);writer.Flush();}catch(IOException){}}
                return 6;
            }
        }
    }
    public static T Call<T>(Request request,CancellationToken cancel,Func<string,Stream,T> receive){
        string token=Guid.NewGuid().ToString("N");
        var security=new PipeSecurity();security.SetAccessRuleProtection(true,false);
        foreach(var sid in new[]{WindowsIdentity.GetCurrent().User,new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid,null)})
            security.AddAccessRule(new PipeAccessRule(sid,PipeAccessRights.FullControl,AccessControlType.Allow));
        using(var pipe=new NamedPipeServerStream("RecoverX-"+token,PipeDirection.InOut,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous,65536,1048576,security))
        using(cancel.Register(()=>pipe.Dispose())){
            var info=new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName,"--reader "+token+" "+Process.GetCurrentProcess().Id){
                UseShellExecute=true,Verb="runas",WorkingDirectory=AppDomain.CurrentDomain.BaseDirectory};
            using(var child=Process.Start(info)){
                var connect=pipe.BeginWaitForConnection(null,null);
                while(!connect.AsyncWaitHandle.WaitOne(100)){
                    cancel.ThrowIfCancellationRequested();if(child.HasExited)throw new IOException("Windows could not start the USB reader.");
                }
                pipe.EndWaitForConnection(connect);uint pid;
                if(!GetNamedPipeClientProcessId(pipe.SafePipeHandle,out pid)||pid!=child.Id)throw new IOException("USB reader identity mismatch.");
                var writer=new BinaryWriter(pipe);writer.Write(Json.Write(request));writer.Flush();
                var reader=new BinaryReader(pipe);
                if(!reader.ReadBoolean())throw new IOException(reader.ReadString());
                T result=receive(reader.ReadString(),pipe);
                if(!child.WaitForExit(10000)||child.ExitCode!=0)throw new IOException("The USB reader stopped. Keep the incomplete image for diagnosis and reconnect the device.");
                return result;
            }
        }
    }
}
public static class Acquisition {
    public static string CopyExact(Stream input,Stream output,long length,CancellationToken stop,Action<long,long> progress){
        if(length<=0)throw new IOException("The source is empty.");
        byte[] buffer=new byte[1024*1024];long pos=0;var timer=Stopwatch.StartNew();
        using(var hash=SHA256.Create()){
            while(pos<length){
                stop.ThrowIfCancellationRequested();
                int read=input.Read(buffer,0,(int)Math.Min(buffer.Length,length-pos));
                if(read<=0)throw new EndOfStreamException("The source disconnected or ended early. The incomplete image cannot be scanned.");
                output.Write(buffer,0,read);hash.TransformBlock(buffer,0,read,buffer,0);pos+=read;
                if(timer.ElapsedMilliseconds>=120||pos==length){progress(pos,length);timer.Restart();}
            }
            stop.ThrowIfCancellationRequested();hash.TransformFinalBlock(buffer,0,0);
            return BitConverter.ToString(hash.Hash).Replace("-","").ToLowerInvariant();
        }
    }
    public static string Acquire(string folder,UsbDisk disk,string image,int sector,string method,CancellationToken stop,Action<string,long,long> notify,Action<string> created){
        folder=Storage.LocalFolder(folder);
        if(disk==null)Storage.ValidateImageDestination(folder);
        long length=disk==null?new FileInfo(image).Length:disk.Size;
        long reserve=checked(length+64L*1024*1024);
        var drive=new DriveInfo(Path.GetPathRoot(folder));
        if(drive.AvailableFreeSpace<reserve)throw new IOException("Choose a destination with at least "+Format.Size(reserve)+" free for this method.");
        if(drive.DriveFormat.Equals("FAT32",StringComparison.OrdinalIgnoreCase) && length>=4294967296L)throw new IOException("FAT32 cannot store this image. Choose an NTFS or exFAT destination.");
        var caseDir=Path.Combine(folder,"RecoverX-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));
        string part=Path.Combine(caseDir,"evidence.partial"), sha=null;
        var clock=Stopwatch.StartNew();
        Action<Stream> capture=input=>{
            stop.ThrowIfCancellationRequested();Storage.LocalFolder(folder);
            Directory.CreateDirectory(caseDir);created(caseDir);
            using(var file=new FileStream(part,FileMode.CreateNew,FileAccess.Write,FileShare.Read,1024*1024)){
                sha=CopyExact(input,file,length,stop,(a,b)=>notify(disk==null?"Copying the disk image":"Reading the selected USB",a,b));file.Flush(true);
            }
        };
        try{
            if(disk==null){
                if(!new[]{".img",".raw",".bin",".dd"}.Contains(Path.GetExtension(image).ToLowerInvariant()))throw new IOException("Choose a raw disk image.");
                using(var input=new FileStream(image,FileMode.Open,FileAccess.Read,FileShare.Read)){capture(input);}
            }else{
                Broker.Call(new Request{op="acquire",identity=disk.Identity,directory=folder},stop,(header,stream)=>{
                    var current=Json.Read<UsbDisk>(header);
                    if(current.Identity!=disk.Identity||current.Size!=length)throw new IOException("The USB identity changed.");
                    capture(stream);return true;
                });
            }
            stop.ThrowIfCancellationRequested();
            File.Move(part,Path.Combine(caseDir,"evidence.img"));
            Json.Save(Path.Combine(caseDir,"acquisition.json"),new{status="complete",source=disk==null?"Disk image":"Physical USB",
                device=disk,image_path=image,bytes=length,sha256=sha,sector=sector,seconds=clock.Elapsed.TotalSeconds,utc=DateTime.UtcNow.ToString("o")});
            return caseDir;
        }catch(Exception e){
            if(Directory.Exists(caseDir))Json.Save(Path.Combine(caseDir,"acquisition-incomplete.json"),new{status=stop.IsCancellationRequested?"cancelled":"incomplete",error=e.Message,expected=length,received=File.Exists(part)?new FileInfo(part).Length:0});
            throw;
        }
    }
}
public static class Format {
    public static string Size(long bytes){string[] units={"B","KiB","MiB","GiB","TiB"};double n=bytes;int u=0;while(n>=1024&&u<units.Length-1){n/=1024;u++;}return n.ToString(u==0?"0":"0.#")+" "+units[u];}
}
}
