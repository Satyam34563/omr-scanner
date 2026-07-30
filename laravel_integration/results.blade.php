{{-- Copy to resources/views/omr/results.blade.php --}}
@extends('layouts.app')

@section('content')
<div class="max-w-4xl mx-auto py-10">
    <h1 class="text-xl font-semibold mb-4">OMR Results</h1>

    @if ($errors->has('omr'))
        <div class="bg-red-50 text-red-700 border border-red-200 rounded p-3 mb-4">
            {{ $errors->first('omr') }}
        </div>
    @endif

    @if ($resolveResult)
        <div class="bg-green-50 text-green-800 border border-green-200 rounded p-3 mb-4 text-sm">
            {{ $resolveResult['num_resolved'] }} sheet(s) resolved.
            @if (!empty($resolveResult['still_invalid']))
                {{ count($resolveResult['still_invalid']) }} entered roll number(s) still weren't found - see below.
            @endif
        </div>
    @endif

    <div class="bg-gray-50 border rounded p-4 mb-6 grid grid-cols-3 gap-4 text-center">
        <div>
            <div class="text-2xl font-bold">{{ $summary['num_processed'] ?? 0 }}</div>
            <div class="text-sm text-gray-500">Sheets processed</div>
        </div>
        <div>
            <div class="text-2xl font-bold">{{ $summary['num_resolved'] ?? 0 }}</div>
            <div class="text-sm text-gray-500">Matched to a student</div>
        </div>
        <div>
            <div class="text-2xl font-bold">{{ $summary['num_pending_review'] ?? 0 }}</div>
            <div class="text-sm text-gray-500">Need manual roll review</div>
        </div>
    </div>

    <h2 class="font-medium mb-2">Download</h2>
    <ul class="space-y-2 mb-6">
        @foreach ($availableFiles as $file)
            <li>
                <a href="{{ route('omr.download', ['job' => $job, 'file' => $file]) }}"
                   class="text-blue-600 underline">
                    {{ $file }}
                </a>
            </li>
        @endforeach
    </ul>

    @if (!empty($summary['pending_review']))
        <h2 class="font-medium mb-2">Needs Roll Number Review ({{ count($summary['pending_review']) }})</h2>
        <p class="text-sm text-gray-500 mb-3">
            Look at each roll-number grid and type in the correct roll number, then submit.
            Leave a row blank to skip it for now - you can come back and finish it later.
        </p>

        <form method="POST" action="{{ route('omr.resolve', ['job' => $job]) }}" class="mb-8">
            @csrf
            <table class="w-full border text-sm mb-4">
                <thead>
                    <tr class="bg-gray-100 text-left">
                        <th class="p-2">Sheet</th>
                        <th class="p-2">Roll Number Grid</th>
                        <th class="p-2">Why it needs review</th>
                        <th class="p-2">Correct Roll No</th>
                    </tr>
                </thead>
                <tbody>
                    @foreach ($summary['pending_review'] as $entry)
                        <tr class="border-t align-top">
                            <td class="p-2 font-mono text-xs">{{ $entry['filename'] }}</td>
                            <td class="p-2">
                                @if (!empty($entry['image_filename']))
                                    <img src="{{ route('omr.pendingImage', ['job' => $job, 'filename' => $entry['image_filename']]) }}"
                                         alt="Roll number grid for {{ $entry['filename'] }}"
                                         class="max-w-[240px] border rounded">
                                @else
                                    <span class="text-gray-400">(no image)</span>
                                @endif
                            </td>
                            <td class="p-2 text-gray-600">{{ $entry['reason'] }}</td>
                            <td class="p-2">
                                <input
                                    type="text"
                                    name="corrections[{{ $entry['filename'] }}]"
                                    value="{{ old('corrections.' . $entry['filename'], $entry['last_attempted_roll'] ?? '') }}"
                                    placeholder="{{ $entry['detected_roll'] ?: 'e.g. 220101' }}"
                                    class="border rounded p-1 w-32"
                                >
                            </td>
                        </tr>
                    @endforeach
                </tbody>
            </table>
            <button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded">
                Submit corrections
            </button>
        </form>
    @endif

    @if (!empty($summary['warnings']))
        <h2 class="font-medium mb-2">Warnings ({{ count($summary['warnings']) }})</h2>
        <ul class="text-sm text-gray-700 space-y-1 list-disc list-inside">
            @foreach ($summary['warnings'] as $warning)
                <li>{{ $warning }}</li>
            @endforeach
        </ul>
    @endif

    <div class="mt-6">
        <a href="{{ route('omr.form') }}" class="text-sm text-gray-500 underline">Process another batch</a>
    </div>
</div>
@endsection
