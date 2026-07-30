{{-- Copy to resources/views/omr/results.blade.php --}}
@extends('layouts.app')

@section('content')
<div class="max-w-2xl mx-auto py-10">
    <h1 class="text-xl font-semibold mb-4">OMR Results</h1>

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
