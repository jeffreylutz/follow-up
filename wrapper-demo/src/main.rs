//! xwrap — Rust command wrapper for a licensed executable.
//!
//! Recipes are baked in at build time (commands.toml) and surface as
//! subcommands; ops settings load from config.toml + XWRAP_* env at runtime.

mod binary;
mod commands;
mod config;
mod license;
mod limiter;
mod runner;
mod update;

use anyhow::Result;
use clap::{Arg, ArgAction, Command};
use std::path::PathBuf;

/// clap subcommand names must be `&'static str`. Recipe names come from the
/// embedded manifest and live for the whole program, so leaking them is fine.
fn leak(s: &str) -> &'static str {
    Box::leak(s.to_string().into_boxed_str())
}

fn build_cli(manifest: &commands::Manifest) -> Command {
    let mut app = Command::new("xwrap")
        .about(format!(
            "Wrapper for {} — recipes baked in at build time",
            manifest.wrapped.name
        ))
        .subcommand_required(true)
        .arg_required_else_help(true)
        .arg(
            Arg::new("config")
                .long("config")
                .global(true)
                .value_name("PATH")
                .help("Path to runtime config.toml"),
        );

    // One subcommand per baked-in recipe.
    for recipe in &manifest.commands {
        app = app.subcommand(
            Command::new(leak(&recipe.name))
                .about(recipe.about.clone())
                .arg(
                    Arg::new("extra")
                        .action(ArgAction::Append)
                        .num_args(0..)
                        .trailing_var_arg(true)
                        .allow_hyphen_values(true)
                        .help("Extra args appended to the wrapped tool"),
                ),
        );
    }

    app.subcommand(Command::new("list").about("List the built-in recipes"))
        .subcommand(Command::new("self-update").about("Force a self-update from Nexus"))
}

fn config_path(matches: &clap::ArgMatches) -> Option<PathBuf> {
    matches
        .get_one::<String>("config")
        .or_else(|| {
            matches
                .subcommand()
                .and_then(|(_, sub)| sub.get_one::<String>("config"))
        })
        .map(PathBuf::from)
}

fn main() -> Result<()> {
    let manifest = commands::Manifest::load();
    let matches = build_cli(&manifest).get_matches();
    let cfg = config::Config::load(config_path(&matches).as_deref())?;

    match matches.subcommand() {
        Some(("list", _)) => {
            for recipe in &manifest.commands {
                println!("{:<12} {}", recipe.name, recipe.about);
            }
            Ok(())
        }
        Some(("self-update", _)) => update::force_update(&cfg),
        Some((name, sub)) => {
            // Auto self-update on run (throttled, fail-open; may re-exec and not return).
            update::maybe_self_update(&cfg)?;

            let recipe = manifest
                .recipe(name)
                .expect("clap restricts subcommands to known recipes");
            let extra: Vec<String> = sub
                .get_many::<String>("extra")
                .map(|vals| vals.cloned().collect())
                .unwrap_or_default();

            let code = runner::run_recipe(&manifest, recipe, &cfg, &extra)?;
            std::process::exit(code);
        }
        None => unreachable!("subcommand_required"),
    }
}
