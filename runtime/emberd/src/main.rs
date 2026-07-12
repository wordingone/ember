// goal_id: EMBER-01
// workstream_id: EMBER-01A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use emberd::{rpc::serve_named_pipe, Daemon};
use std::path::PathBuf;

fn usage() -> &'static str {
    "usage: emberd serve --db <path> --pipe <\\\\.\\pipe\\name>"
}

fn parse_serve_args() -> Result<(PathBuf, String), String> {
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() != Some("serve") {
        return Err(usage().into());
    }
    let mut db = None;
    let mut pipe = None;
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {flag}\n{}", usage()))?;
        match flag.as_str() {
            "--db" => db = Some(PathBuf::from(value)),
            "--pipe" => pipe = Some(value),
            _ => return Err(format!("unknown argument {flag}\n{}", usage())),
        }
    }
    Ok((
        db.ok_or_else(|| format!("missing --db\n{}", usage()))?,
        pipe.ok_or_else(|| format!("missing --pipe\n{}", usage()))?,
    ))
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let (db, pipe) = parse_serve_args().map_err(std::io::Error::other)?;
    let daemon = Daemon::open(&db)?;
    daemon.reconcile()?;
    serve_named_pipe(&daemon, &pipe)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("emberd: {error}");
        std::process::exit(1);
    }
}
