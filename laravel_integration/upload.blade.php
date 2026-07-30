{{-- Copy to resources/views/omr/upload.blade.php --}}
{{-- Adjust @extends/@section to match your app's actual layout. --}}
@extends('layouts.app')

@section('content')
<div class="max-w-xl mx-auto py-10">
    <h1 class="text-xl font-semibold mb-4">Check OMR Answer Sheets</h1>

    @if ($errors->has('omr'))
        <div class="bg-red-50 text-red-700 border border-red-200 rounded p-3 mb-4">
            {{ $errors->first('omr') }}
        </div>
    @endif

    <form method="POST" action="{{ route('omr.process') }}" enctype="multipart/form-data" class="space-y-4">
        @csrf

        <div>
            <label class="block text-sm font-medium mb-1">Scanned sheets (single PDF, one page per sheet)</label>
            <input type="file" name="scans_pdf" accept=".pdf" required class="block w-full border rounded p-2">
            @error('scans_pdf') <p class="text-red-600 text-sm mt-1">{{ $message }}</p> @enderror
        </div>

        <div>
            <label class="block text-sm font-medium mb-1">Answer key (.xlsx)</label>
            <input type="file" name="answer_key" accept=".xlsx" required class="block w-full border rounded p-2">
            @error('answer_key') <p class="text-red-600 text-sm mt-1">{{ $message }}</p> @enderror
        </div>

        <button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded">
            Process
        </button>
    </form>

    <p class="text-sm text-gray-500 mt-4">
        Large batches can take a little while - the page will wait for processing to finish before showing results.
    </p>
</div>
@endsection
