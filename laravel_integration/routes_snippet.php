<?php
/**
 * Add these routes to routes/web.php (inside your existing 'auth'
 * middleware group, so only logged-in staff can reach them).
 *
 * They assume App\Http\Controllers\OmrController.php has been added
 * to your app (see OmrController.php in this same folder).
 */

use App\Http\Controllers\OmrController;

Route::middleware(['auth'])->prefix('omr')->name('omr.')->group(function () {
    Route::get('/', [OmrController::class, 'showForm'])->name('form');
    Route::post('/process', [OmrController::class, 'process'])->name('process');
    Route::get('/results/{job}', [OmrController::class, 'showResults'])->name('results');
    Route::get('/results/{job}/download/{file}', [OmrController::class, 'download'])->name('download');
    Route::get('/results/{job}/image/{filename}', [OmrController::class, 'pendingImage'])->name('pendingImage');
    Route::post('/results/{job}/resolve', [OmrController::class, 'resolve'])->name('resolve');
});
