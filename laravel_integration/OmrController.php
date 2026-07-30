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
 * Each processing run gets a random UUID "job" folder under
 * storage/app/private/omr_jobs/{job}/, holding the extracted result
 * files. There's no database table for jobs - the UUID being
 * unguessable plus the 'auth' middleware is enough protection for a
 * single-school internal tool. If multiple staff accounts shouldn't
 * be able to see each other's batches, add an `omr_jobs` table
 * (owner_id, job_uuid, created_at) and check ownership in
 * showResults()/download() below.
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
            $response = Http::timeout(180) // OMR processing + upload/download time for a big batch
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
        $jobDir = "private/omr_jobs/{$job}";
        $zipPath = storage_path("app/{$jobDir}.zip");

        Storage::makeDirectory($jobDir);
        file_put_contents($zipPath, $response->body());

        $zip = new ZipArchive();
        $zip->open($zipPath);
        $zip->extractTo(storage_path("app/{$jobDir}"));
        $zip->close();
        unlink($zipPath);

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
        $jobDir = "private/omr_jobs/{$job}";
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
        ]);
    }

    public function download(string $job, string $file)
    {
        if (!Str::isUuid($job) || !in_array($file, self::ALLOWED_FILES, true)) {
            abort(404);
        }
        $path = "private/omr_jobs/{$job}/{$file}";
        if (!Storage::exists($path)) {
            abort(404);
        }
        return Storage::download($path);
    }
}
