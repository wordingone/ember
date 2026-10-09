param([string]$SourcePath,[string]$ReceiptPath)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $ReceiptPath){throw 'RECEIPT_ALREADY_EXISTS'}
$helper=@'
public static class CapSnapshotFixture {
    static System.Type T=typeof(NikoSelectedProjection.Runner);
    static System.Reflection.BindingFlags F=System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Static;
    static NikoSelectedProjection.Runner.Binding B;
    static long Rows,Ids,Members;
    static object State;
    public static void Row(object value) {
        Rows++;
        var v=(System.Collections.Generic.Dictionary<string,string>)value.GetType().GetField("V").GetValue(value);
        if(v.ContainsKey("kind")&&v["kind"]=="membership") { Ids++;if(Ids<=8)Members++; }
        if(Rows==64)B.max_private_bytes=1;
    }
    public static System.Collections.Generic.Dictionary<string,long> Counts() {
        return new System.Collections.Generic.Dictionary<string,long>{{"membership_id_set_count",Ids},{"retained_member_object_count",Members},{"selected_membership_id_count",8}};
    }
    static void Reset() {
        T.GetField("PeakPrivate",F).SetValue(null,0L);T.GetField("PrivateSampleCount",F).SetValue(null,0L);T.GetField("PrivateRowsSinceSample",F).SetValue(null,0);
        ((System.Collections.IList)T.GetField("DiagnosticSnapshots",F).GetValue(null)).Clear();
        Rows=Ids=Members=0;
        State=System.Activator.CreateInstance(T.GetNestedType("ScanState",System.Reflection.BindingFlags.NonPublic));
        State.GetType().GetField("PassName").SetValue(State,"pass1");
        B=new NikoSelectedProjection.Runner.Binding{max_private_bytes=536870912,max_wall_seconds=900,max_total_bytes_read=10485760,marker_path="C:/NONEXISTENT-CAP-FIXTURE-MARKER"};
    }
    public static string Run(string input) {
        Reset();B.owner_reported_export_bytes=new System.IO.FileInfo(input).Length;B.max_export_bytes=10485760;
        var method=T.GetMethod("Scan",F);
        var callback=System.Delegate.CreateDelegate(method.GetParameters()[6].ParameterType,typeof(CapSnapshotFixture).GetMethod("Row"));
        var counts=new System.Func<System.Collections.Generic.Dictionary<string,long>>(Counts);
        System.Exception caught=null;
        using(var stream=new System.IO.FileStream(input,System.IO.FileMode.Open,System.IO.FileAccess.Read,System.IO.FileShare.Read)) {
            object[] args={stream,B,System.Diagnostics.Stopwatch.StartNew(),0L,false,false,callback,State,counts};
            try { method.Invoke(null,args); } catch(System.Exception ex){caught=ex;}
        }
        if(caught==null)throw new System.InvalidOperationException("CAP_NOT_TRIGGERED");
        return System.Text.Json.JsonSerializer.Serialize(NikoSelectedProjection.Runner.CaptureFailure(caught,0));
    }
    public static string Direct() {
        Reset();B.max_private_bytes=1;Ids=64;Members=8;
        State.GetType().GetField("Rows").SetValue(State,64L);
        System.Exception caught=null;
        try { T.GetMethod("CaptureDiagnosticSnapshot",F).Invoke(null,new object[]{"direct_cap",State,1L,new System.Func<System.Collections.Generic.Dictionary<string,long>>(Counts)}); }catch(System.Exception ex){caught=ex;}
        if(caught==null)throw new System.InvalidOperationException("DIRECT_CAP_NOT_TRIGGERED");
        return System.Text.Json.JsonSerializer.Serialize(NikoSelectedProjection.Runner.CaptureFailure(caught,0));
    }
}
'@
$r=[Collections.Generic.List[object]]::new()
for($i=0;$i -lt 96;$i++){$r.Add([ordered]@{kind='membership';id=('m-'+$i);exact_sha256=('{0:x64}' -f [long]($i+1))})}
$fixture=Join-Path (Split-Path -Parent $ReceiptPath) ((Split-Path -Leaf $ReceiptPath)+'.input.json')
[IO.File]::WriteAllText($fixture,(ConvertTo-Json -InputObject ([ordered]@{records=$r.ToArray();edges=@()}) -Depth 6 -Compress),[Text.UTF8Encoding]::new($false))
Add-Type -TypeDefinition ([IO.File]::ReadAllText($SourcePath)+[Environment]::NewLine+$helper)
$rows=[CapSnapshotFixture]::Run($fixture)|ConvertFrom-Json
$direct=[CapSnapshotFixture]::Direct()|ConvertFrom-Json
$fail=@($rows.diagnostic_snapshots|Where-Object{$_.checkpoint -eq 'row_failure' -and $_.pass_name -eq 'pass1' -and [long]$_.pass_rows -eq 64})
$ds=@($direct.diagnostic_snapshots|Where-Object{$_.checkpoint -eq 'direct_cap'})
$checks=[ordered]@{
 row_guard_CAP_PRIVATE=((ConvertTo-Json $rows -Depth 20 -Compress).Contains('CAP_PRIVATE:metadata_row'))
 row_failure_snapshot_retained=($fail.Count -eq 1)
 row_failure_index_counts=($fail.Count -eq 1 -and [long]$fail[0].membership_id_set_count -eq 64 -and [long]$fail[0].retained_member_object_count -eq 8 -and [long]$fail[0].selected_membership_id_count -eq 8)
 row_failure_private_observation_above_cap=($fail.Count -eq 1 -and [long]$fail[0].private_usage_bytes -gt 1)
 direct_cap_snapshot_retained=($ds.Count -eq 1)
 direct_guard_CAP_PRIVATE=((ConvertTo-Json $direct -Depth 20 -Compress).Contains('CAP_PRIVATE:diagnostic_snapshot:direct_cap'))
 measured_peak_retained=([long]$rows.private_bytes_peak_observed -gt 1 -and [long]$rows.private_usage_sample_count -gt 0)
 production_source_not_lowered=([IO.File]::ReadAllText($SourcePath) -notmatch 'max_private_bytes=1')
}
$pass=(@($checks.Values|Where-Object{$_ -eq $false}).Count -eq 0)
$record=[ordered]@{schema='niko.cap_failure_snapshot.synthetic.v1';status=if($pass){'PASS'}else{'EXPECTED_RED_MISSING_CAP_SNAPSHOT'};observed_utc=[DateTime]::UtcNow.ToString('o');source_path=$SourcePath;source_sha256=(Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash.ToLowerInvariant();test_threshold_bytes=1;production_cap_bytes=536870912;test_scope='C-only real Scan row check at64; fixture callback lowers only synthetic binding; separate direct diagnostic cap; no production input/run';checks=$checks;row_refusal_diagnostics=$rows;direct_refusal_diagnostics=$direct}
[IO.File]::WriteAllText($ReceiptPath,(ConvertTo-Json $record -Depth 20),[Text.UTF8Encoding]::new($false))
Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256|Select-Object Path,Hash|ConvertTo-Json
Write-Output ($checks|ConvertTo-Json)
if(-not $pass){exit 1}
