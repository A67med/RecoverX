using System;
using System.Reflection;
using System.Windows;
[assembly:AssemblyTitle("RecoverX Recovery Studio")]
[assembly:AssemblyProduct("RecoverX")]
[assembly:AssemblyVersion("1.0.0.0")]
[assembly:AssemblyFileVersion("1.0.0.0")]
namespace RecoverX {
public static class Program {
    [STAThread] public static int Main(string[] args){
        if(args.Length==3 && args[0]=="--reader"){
            int parent;if(!Int32.TryParse(args[2],out parent))return 2;
            try{return Broker.Serve(args[1],parent);}catch{return 8;}
        }
        var app=new Application();
        app.DispatcherUnhandledException+=(s,e)=>{MessageBox.Show(e.Exception.Message,"RecoverX",MessageBoxButton.OK,MessageBoxImage.Error);e.Handled=true;};
        return app.Run(new Studio());
    }
}
}
