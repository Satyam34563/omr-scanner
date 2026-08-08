<?php
/**
 * Copy this file to app/Http/Controllers/OmrController.php.
 *
 * Talks to the OMR Checker Python API (api.py, running on the same
 * server at 127.0.0.1:8001) over plain HTTP. Laravel's own 'auth'
 * middleware (see routes_snippet.php) is what actually gates access -
 * the Python API has no login of its own and trusts anything that can
 * reach it on localhost, so nothing outside this server should ever
 * be able to reach that port.
 *
 * Each processing run gets a random UUID "job" folder under the
 * default 'local' filesystem disk, at omr_jobs/{job}/, holding the
 * extracted result files. Everything goes through the Storage facade
 * rather than raw storage_path()/file_put_contents() calls, so it
 * resolves correctly regardless of where the 'local' disk's root
 * actually points (Laravel 11+ defaults it to storage/app/private,
 * older versions to storage/app - mixing raw paths with Storage:: was
 * a real bug in an earlier version of this file that caused
 * "file_put_contents(...): No such file or directory"). The 'local'
 * disk is never web-servable either way, unlike 'public'.
 *
 * Sheets whose roll number couldn't be read/matched automatically show
 * up in $summary['pending_review'] (an array of filename/detected_roll
 * /reason/image_filename, written by api.py into summary.json). The
 * results page renders those as a table with each sheet's roll-grid
 * image and a text box - resolve() posts whatever's been typed in as
 * plain JSON to the Python API's POST /resolve, which rescores against
 * the answers already saved in results.xlsx (no re-scanning). No
 * Excel round-trip needed for this from the browser's side; the
 * Python API's /resolve endpoint still accepts a plain results.xlsx +
 * JSON corrections either way, so tools/resolve_manual_roll.py (the
 * Excel-based CLI path) and this web form both call the same
 * underlying logic without knowing about each other.
 *
 * There's no database table for jobs - the UUID being unguessable
 * plus the 'auth' middleware is enough protection for a single-school
 * internal tool. If multiple staff accounts shouldn't be able to see
 * each other's batches, add an `omr_jobs` table (owner_id, job_uuid,
 * created_at) and check ownership in showResults()/download() below.
 */

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use ZipArchive;

class OmrController extends Controller
{
    // Files we allow a user to download back out of a job folder.
    // Keeps the download route from being tricked into serving an
    // arbitrary path.
    private const ALLOWED_FILES = [
        'results.xlsx',
        'student_reports.pdf',
        'bubble_overlay.pdf',
        'manual_review.xlsx',
    ];

    public function showForm()
    {
        return view('omr.upload');
    }

    public function process(Request $request)
    {
        $request->validate([
            'scans_pdf'  => ['required', 'file', 'mimes:pdf', 'max:51200'],   // 50 MB
            'answer_key' => ['required', 'file', 'mimes:xlsx', 'max:5120'],   // 5 MB
        ]);

        $omrApiUrl = config('services.omr.url');

        try {
            $response = Http::timeout(5400) // OMR processing + upload/download time for a big batch
                ->attach(
                    'scans_pdf',
                    fopen($request->file('scans_pdf')->getRealPath(), 'r'),
                    $request->file('scans_pdf')->getClientOriginalName()
                )
                ->attach(
                    'answer_key',
                    fopen($request->file('answer_key')->getRealPath(), 'r'),
                    $request->file('answer_key')->getClientOriginalName()
                )
                ->post("{$omrApiUrl}/process");
        } catch (\Illuminate\Http\Client\ConnectionException $e) {
            return back()->withErrors([
                'omr' => 'Could not reach the OMR processing service. Is it running? '
                    . '(systemctl status omr-checker on the server)',
            ]);
        }

        if ($response->failed()) {
            $detail = $response->json('detail') ?? $response->body();
            return back()->withErrors(['omr' => "OMR processing failed: {$detail}"]);
        }

        // Response body is the ZIP api.py builds (results.xlsx, bubble_overlay.pdf,
        // manual_review.xlsx, student_reports.pdf if any sheets resolved, summary.json).
        $job = (string) Str::uuid();
        $jobDir = "omr_jobs/{$job}";

        Storage::makeDirectory($jobDir);
        Storage::put("{$jobDir}.zip", $response->body());

        // ZipArchive needs a real filesystem path, not a Storage stream -
        // Storage::path() resolves to wherever the 'local' disk's root
        // actually is, so this stays correct across Laravel versions.
        $zip = new ZipArchive();
        $zip->open(Storage::path("{$jobDir}.zip"));
        $zip->extractTo(Storage::path($jobDir));
        $zip->close();
        Storage::delete("{$jobDir}.zip");

        $summary = json_decode(
            Storage::get("{$jobDir}/summary.json") ?? '{}',
            true
        );

        return redirect()->route('omr.results', ['job' => $job])->with('summary', $summary);
    }

    public function showResults(Request $request, string $job)
    {
        if (!Str::isUuid($job)) {
            abort(404);
        }
        $jobDir = "omr_jobs/{$job}";
        if (!Storage::exists("{$jobDir}/summary.json")) {
            abort(404, 'Results not found - they may have been cleaned up already.');
        }

        $summary = json_decode(Storage::get("{$jobDir}/summary.json"), true);

        $availableFiles = collect(self::ALLOWED_FILES)
            ->filter(fn ($name) => Storage::exists("{$jobDir}/{$name}"));

        return view('omr.results', [
            'job' => $job,
            'summary' => $summary,
            'availableFiles' => $availableFiles,
            'resolveResult' => session('resolveResult'),
        ]);
    }

    public function download(string $job, string $file)
    {
        if (!Str::isUuid($job) || !in_array($file, self::ALLOWED_FILES, true)) {
            abort(404);
        }
        $path = "omr_jobs/{$job}/{$file}";
        if (!Storage::exists($path)) {
            abort(404);
        }
        return Storage::download($path);
    }

    // Streams a pending sheet's roll-grid crop image inline (for an
    // <img> tag on the review table), not as a download. Only serves
    // filenames that actually appear in this job's own pending_review
    // list - keeps the route from being used to read arbitrary files
    // out of the job folder.
    public function pendingImage(string $job, string $filename)
    {
        if (!Str::isUuid($job)) {
            abort(404);
        }
        $jobDir = "omr_jobs/{$job}";
        $summary = json_decode(Storage::get("{$jobDir}/summary.json") ?? '{}', true);
        $allowed = collect($summary['pending_review'] ?? [])->pluck('image_filename')->filter();
        if (!$allowed->contains($filename)) {
            abort(404);
        }

        $path = "{$jobDir}/pending_review/{$filename}";
        if (!Storage::exists($path)) {
            abort(404);
        }
        return Storage::response($path);
    }

    // Takes whatever roll numbers were typed into the review table
    // (corrections[filename] = roll_no, blanks allowed - anything left
    // blank is just skipped, not an error) and forwards them as JSON
    // to the Python API's POST /resolve, along with this job's current
    // results.xlsx. Overwrites the job folder with the response
    // (updated results.xlsx + rebuilt student_reports.pdf) and updates
    // summary.json so the review table reflects what's still pending.
    public function resolve(Request $request, string $job)
    {
        if (!Str::isUuid($job)) {
            abort(404);
        }
        $jobDir = "omr_jobs/{$job}";
        if (!Storage::exists("{$jobDir}/results.xlsx")) {
            abort(404, 'Results not found - they may have been cleaned up already.');
        }

        $corrections = array_filter(
            (array) $request->input('corrections', []),
            fn ($value) => trim((string) $value) !== ''
        );
        if (empty($corrections)) {
            return back()->withErrors(['omr' => 'Enter at least one roll number before submitting.']);
        }

        $omrApiUrl = config('services.omr.url');

        try {
            $response = Http::timeout(1200)
                ->attach('results_xlsx', Storage::get("{$jobDir}/results.xlsx"), 'results.xlsx')
                ->post("{$omrApiUrl}/resolve", [
                    'corrections' => json_encode($corrections),
                ]);
        } catch (\Illuminate\Http\Client\ConnectionException $e) {
            return back()->withErrors(['omr' => 'Could not reach the OMR processing service.']);
        }

        if ($response->failed()) {
            $detail = $response->json('detail') ?? $response->body();
            return back()->withErrors(['omr' => "Resolve failed: {$detail}"]);
        }

        $tmpZip = tempnam(sys_get_temp_dir(), 'omr_resolve_') . '.zip';
        file_put_contents($tmpZip, $response->body());

        $zip = new ZipArchive();
        $zip->open($tmpZip);
        $resolveSummary = json_decode($zip->getFromName('resolve_summary.json'), true);
        for ($i = 0; $i < $zip->numFiles; $i++) {
            $name = $zip->getNameIndex($i);
            if ($name === 'resolve_summary.json') {
                continue;
            }
            Storage::put("{$jobDir}/{$name}", $zip->getFromIndex($i));
        }
        $zip->close();
        unlink($tmpZip);

        // Drop newly-resolved filenames from pending_review and update
        // the reason/last-attempted-roll for ones that are still stuck,
        // so the reviewer sees why their last guess didn't work.
        $summary = json_decode(Storage::get("{$jobDir}/summary.json"), true);
        $resolvedFilenames = collect($resolveSummary['resolved'] ?? [])->pluck('filename');
        $stillInvalidByFilename = collect($resolveSummary['still_invalid'] ?? [])->keyBy('filename');

        $summary['pending_review'] = collect($summary['pending_review'] ?? [])
            ->reject(fn ($entry) => $resolvedFilenames->contains($entry['filename']))
            ->map(function ($entry) use ($stillInvalidByFilename) {
                if ($stillInvalidByFilename->has($entry['filename'])) {
                    $entry['reason'] = $stillInvalidByFilename[$entry['filename']]['reason'];
                    $entry['last_attempted_roll'] = $stillInvalidByFilename[$entry['filename']]['entered_roll'];
                }
                return $entry;
            })
            ->values()
            ->all();
        $summary['num_pending_review'] = count($summary['pending_review']);
        $summary['num_resolved'] = ($summary['num_resolved'] ?? 0) + count($resolveSummary['resolved'] ?? []);
        Storage::put("{$jobDir}/summary.json", json_encode($summary, JSON_PRETTY_PRINT));

        return redirect()->route('omr.results', ['job' => $job])->with('resolveResult', $resolveSummary);
    }
}
