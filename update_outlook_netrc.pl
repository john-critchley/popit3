#!/usr/bin/perl
use strict;
use warnings;
use LWP::UserAgent;
use HTTP::Date qw(time2str);
use Net::Netrc;

my $netrc = "$ENV{HOME}/.netrc";
my $host  = 'webdav.critchley.biz';
my $url   = "https://$host/private/creds/auth.txt";

my $mtime = (stat $netrc)[9] // 0;

my $mach = Net::Netrc->lookup($host) or die "No netrc entry for $host\n";

my $ua  = LWP::UserAgent->new;
my $req = HTTP::Request->new(GET => $url);
$req->authorization_basic($mach->login, $mach->password);
$req->header('If-Modified-Since' => time2str($mtime));

my $resp = $ua->request($req);
exit 0 if $resp->code == 304;
die "Fetch failed: " . $resp->status_line . "\n" unless $resp->is_success;

my $creds = $resp->decoded_content;

open my $fh, '<', $netrc or die "read $netrc: $!";
my $content = do { local $/; <$fh> };
close $fh;

$content =~ s/^machine outlook\.office365\.com\n(?:(?!machine ).*\n)*//m;

open $fh, '>', $netrc or die "write $netrc: $!";
print $fh $content =~ s/\s*$/\n/r, $creds;
close $fh;

warn "Updated ~/.netrc with fresh outlook credentials\n";
