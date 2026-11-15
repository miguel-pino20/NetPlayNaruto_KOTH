package org.un5.narutonetplay;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Read-only, single-file grant to Android's package installer. */
public final class UpdateProvider extends ContentProvider {
    private File update(Uri uri) {
        if (!"org.un5.narutonetplay.updates".equals(uri.getAuthority())
                || !"/update.apk".equals(uri.getPath()))
            throw new IllegalArgumentException("Unknown update URI");
        return new File(getContext().getFilesDir(), "updates/latest.apk");
    }
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) {
        update(uri);
        return "application/vnd.android.package-archive";
    }
    @Override public Cursor query(Uri uri, String[] projection, String selection,
                                  String[] args, String sort) {
        File file = update(uri);
        String[] columns = projection == null
            ? new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor cursor = new MatrixCursor(columns, 1);
        Object[] row = new Object[columns.length];
        for (int i = 0; i < columns.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) row[i] = "Naruto-Netplay-update.apk";
            else if (OpenableColumns.SIZE.equals(columns[i])) row[i] = file.length();
        }
        cursor.addRow(row);
        return cursor;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(update(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
